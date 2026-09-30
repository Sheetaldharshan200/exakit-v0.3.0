"""Exasol Personal: the local database driven through its own ``exasol`` launcher.

The status decision tree, start, stop, the readiness wait and the
self-heal every SQL-speaking command runs first. Deployment of a brand-new
database (Podman on Linux, reuse and replace questions) stays with the
installer until Phase C; ``deploy`` here is the plain ``exasol install
local`` used by the self-heal on a machine whose deployment vanished.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from exakit.adapters.fs.credentials import CredentialStore
from exakit.adapters.fs.log import Log, NullLog
from exakit.adapters.process.ports import listener_pids, port_in_use, process_age_seconds, process_command, port_holders
from exakit.adapters.process.runner import Runner
from exakit.domain.errors import Failed
from exakit.domain.manifest import Manifest

DEFAULT_PORT = 8563
PROBE_TIMEOUT = 10
REAP_MIN_AGE = 180
READY_TIMEOUT = 150
REBUILD_TIMEOUT = 900


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    state: str            # running | stopped | starting | conflict | interrupted | not deployed | not installed
    port: int
    detail: str = ""


class PersonalRuntime(Protocol):
    def status(self) -> RuntimeStatus: ...
    def running(self) -> bool: ...
    def deployment_exists(self) -> bool: ...
    def start(self, say: Callable[[str], None]) -> None: ...
    def stop(self, say: Callable[[str], None]) -> None: ...
    def wait_ready(self, say: Callable[[str], None], *, budget: int | None = None) -> bool: ...
    def deploy(self, say: Callable[[str], None]) -> None: ...
    def db_port(self) -> int: ...


class PersonalLauncher:
    """The real runtime, over the ``exasol`` binary."""

    def __init__(self, *, bin_dir: Path, deploy_dir: Path, runner: Runner, log: Log | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.bin_dir, self.deploy_dir, self.runner, self.log = bin_dir, deploy_dir, runner, log or NullLog()
        self.env = env or {}

    # --- the launcher --------------------------------------------------------------

    def cli(self) -> str:
        own = self.bin_dir / "exasol"
        if own.exists():
            return str(own)
        return self.runner.which("exasol") or str(own)

    def installed(self) -> bool:
        return (self.bin_dir / "exasol").exists() or bool(self.runner.which("exasol"))

    def _run(self, *args: str, timeout: float = PROBE_TIMEOUT):
        return self.runner.run([self.cli(), *args], timeout=timeout)

    def supports(self, subcommand: str) -> bool:
        done = self._run("--help")
        return bool(re.search(rf"^\s*(-\w,\s*)?{re.escape(subcommand)}(\s|,|$)", done.out, re.M))

    def auto_approve(self, subcommand: str) -> list[str]:
        done = self._run(subcommand, "--help")
        return ["--auto-approve"] if "--auto-approve" in done.out else []

    def launcher_version(self) -> str | None:
        done = self._run("version")
        text = done.out.strip().splitlines()[0].lstrip("v") if done.ok and done.out.strip() else ""
        return text if re.fullmatch(r"[0-9][0-9A-Za-z._+-]*", text) else None

    def launcher_state(self) -> str:
        done = self._run("status", "--json")
        match = re.search(r'"status"\s*:\s*"([^"]*)"', done.out)
        if match:
            return match.group(1).lower()
        done = self._run("status")
        match = re.search(r"^\s*Status:\s*([A-Za-z_]+)", done.out, re.M)
        return match.group(1).lower() if match else ""

    # --- the deployment ----------------------------------------------------------------

    def db_port(self) -> int:
        try:
            text = (self.deploy_dir / "deployment.json").read_text(encoding="utf-8")
            match = re.search(r'"dbPort"\s*:\s*(\d+)', text)
            return int(match.group(1)) if match else DEFAULT_PORT
        except OSError:
            return DEFAULT_PORT

    def deployment_exists(self) -> bool:
        return self.deploy_dir.is_dir() and self._run("info").ok

    def deployed_version(self) -> str | None:
        try:
            return (self.deploy_dir / ".exasolLauncher.version").read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
        try:
            doc = json.loads((self.deploy_dir / ".exasolLauncherState.json").read_text(encoding="utf-8"))
            return doc.get("deploymentVersion") or None
        except (OSError, ValueError):
            return None

    def wedged(self) -> str | None:
        """The interrupted-workflow error when the launcher gave up mid-run, else None."""
        try:
            doc = json.loads((self.deploy_dir / ".exasolLauncherState.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        state = doc.get("currentWorkflowState")
        if isinstance(state, dict) and "interrupted" in state:
            err = state["interrupted"].get("error") if isinstance(state["interrupted"], dict) else None
            return str(err or "interrupted")
        return None

    # --- probes ---------------------------------------------------------------------------

    def tls_answers(self, port: int | None = None) -> bool:
        """A completed TLS handshake on the SQL port: Exasol is listening, not just the port."""
        port = port or self.db_port()
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
                with context.wrap_socket(raw, server_hostname="localhost"):
                    return True
        except (OSError, ssl.SSLError):
            return False

    def _runner_pids(self, port: int) -> list[tuple[int, str]]:
        return [(pid, process_command(pid, self.runner)) for pid in listener_pids(port, self.runner)]

    def _looks_like_our_runner(self, command: str) -> bool:
        return ("mac-runner" in command and "__daemon__" in command) or "exasol-local-runner" in command

    def starting(self, port: int) -> bool:
        for pid, command in self._runner_pids(port):
            age = process_age_seconds(pid, self.runner)
            if self._looks_like_our_runner(command) and age is not None and age < REAP_MIN_AGE:
                return True
        return False

    def status(self) -> RuntimeStatus:
        port = self.db_port()
        if not self.installed():
            return RuntimeStatus("not installed", port)
        if not self.deployment_exists():
            return RuntimeStatus("not deployed", port)
        if port_in_use(port):
            if self.launcher_state() == "stopped":
                return RuntimeStatus("stopped", port)
            if self.tls_answers(port):
                return RuntimeStatus("running", port)
            if self.starting(port):
                return RuntimeStatus("starting", port)
            holders = port_holders(port, self.runner)
            return RuntimeStatus("conflict", port, holders[0].description if holders else "")
        if self.wedged() is not None:
            return RuntimeStatus("interrupted", port, self.wedged() or "")
        return RuntimeStatus("stopped", port)

    def running(self) -> bool:
        port = self.db_port()
        if not port_in_use(port):
            return False
        if self.deployment_exists():
            if self.launcher_state() in ("stopped", "deployment_failed"):
                return False
            return self.tls_answers(port)
        return False

    # --- actions ----------------------------------------------------------------------------

    def reap_orphan(self, port: int, say: Callable[[str], None]) -> bool:
        """Kill a leftover runner of ours holding the port. True when the port is now free."""
        reaped = False
        state = self.launcher_state()
        for pid, command in self._runner_pids(port):
            age = process_age_seconds(pid, self.runner) or 0
            if self._looks_like_our_runner(command) and age >= REAP_MIN_AGE and state in ("", "stopped", "deployment_failed", "interrupted"):
                say(f"Reaping orphaned Exasol runner daemon (pid {pid}) still holding port {port}")
                self.runner.run(["pkill", "-P", str(pid)], timeout=5)
                self.runner.run(["kill", str(pid)], timeout=5)
                reaped = True
        if not reaped:
            return False
        for _ in range(10):
            if not port_in_use(port):
                return True
            time.sleep(0.5)
        for pid in listener_pids(port, self.runner):
            self.runner.run(["kill", "-9", str(pid)], timeout=5)
        time.sleep(1)
        return not port_in_use(port)

    def start(self, say: Callable[[str], None]) -> None:
        if not self.supports("start"):
            say("This launcher version has no explicit start command.")
            say(f"Check the database with: {self.cli()} info")
            return
        if self.launcher_state() == "deployment_failed":
            say("The launcher records this deployment as failed - retrying its deploy instead of a start it would ignore.")
            done = self._run("deploy", *self.auto_approve("deploy"), timeout=1800)
            self.log.line("CMD", f"{self.cli()} deploy -> {done.code}")
            if not done.ok:
                raise Failed("The deployment could not be brought up. Check the log; if it fails the same way, repair with: exakit repair-runtime",
                             remedy="exakit repair-runtime")
            return
        port = self.db_port()
        if self.launcher_state() == "stopped" and port_in_use(port):
            say(f"Clearing a leftover Exasol runner still holding port {port}")
            self.reap_orphan(port, say)
        done = self._run("start", *self.auto_approve("start"), timeout=1800)
        self.log.line("CMD", f"{self.cli()} start -> {done.code}")
        if not done.ok:
            if self.wedged() is not None:
                raise Failed("The database is interrupted and cannot be started - the launcher has to rebuild it. "
                             "Repair it with: exakit repair-runtime (this rebuilds the database from empty; its data is not recoverable).",
                             remedy="exakit repair-runtime")
            if self.status().state == "conflict":
                holders = port_holders(port, self.runner)
                hint = f" ({holders[0].description})" if holders else ""
                raise Failed(f"Port {port} is held by another process{hint}, so the database cannot start. Stop that process, then: exakit start",
                             remedy="exakit start")
            raise Failed("Failed to start the database. Check the log, then retry with 'exakit start'; if it fails the same way, repair with: exakit repair-runtime",
                         remedy="exakit start")

    def stop(self, say: Callable[[str], None]) -> None:
        if not self.supports("stop"):
            say("This launcher version has no explicit stop command.")
            say("To remove the database entirely use: exakit uninstall")
            return
        done = self._run("stop", timeout=600)
        self.log.line("CMD", f"{self.cli()} stop -> {done.code}")
        if not done.ok:
            raise Failed("Failed to stop the database.", remedy="exakit stop")

    def wait_ready(self, say: Callable[[str], None], *, budget: int | None = None) -> bool:
        """Poll the TLS probe every 5 s until the database answers or the budget runs out."""
        env_budget = self.env.get("EXAKIT_PERSONAL_READY_TIMEOUT", "")
        budget = budget or (int(env_budget) if env_budget.isdigit() else READY_TIMEOUT)
        started = time.monotonic()
        last_note = started
        port = self.db_port()
        while time.monotonic() - started < budget:
            if self.tls_answers(port):
                return True
            time.sleep(5)
            if time.monotonic() - last_note >= 30:
                say(f"... waiting for the database to answer ({int(time.monotonic() - started)}s elapsed, ceiling {budget}s; raise it with EXAKIT_PERSONAL_READY_TIMEOUT)")
                last_note = time.monotonic()
        return False

    def wait_ready_or_deploy(self, say: Callable[[str], None]) -> bool:
        if self.wait_ready(say):
            return True
        say("The database did not answer after the launcher accepted the start.")
        say("In some states the launcher's start does nothing and its deploy is the fix - running that now.")
        done = self._run("deploy", *self.auto_approve("deploy"), timeout=1800)
        if not done.ok:
            return False
        return self.wait_ready(say)

    def deploy(self, say: Callable[[str], None]) -> None:
        """A plain ``exasol install local``; the installer's richer flow (Podman, reuse) is Phase C."""
        done = self._run("install", "local", *self.auto_approve("install"), timeout=3600)
        self.log.line("CMD", f"{self.cli()} install local -> {done.code}")
        if not done.ok:
            raise Failed("No database could be deployed (the launcher did not finish). Once it is fixed, re-run the installer.")
        if not self.wait_ready_or_deploy(say):
            raise Failed("The database never answered after deployment. Read the state with 'exakit status', or repair with: exakit repair-runtime",
                         remedy="exakit repair-runtime")

    # --- the record -----------------------------------------------------------------------

    def record(self, manifest: Manifest, credentials: CredentialStore, status: str | None = None) -> str | None:
        """Write the runtime.* keys from the deployment files. Returns a warning when the password could not be read."""
        manifest.set("runtime.type", "personal")
        for key in ("engine", "container", "image", "volume"):
            manifest.delete(f"runtime.{key}")
        deployed = self.deployed_version()
        manifest.set("runtime.version", self.launcher_version() or deployed or manifest.get("runtime.version") or "unknown")
        if deployed:
            manifest.set("runtime.deployment_version", deployed)
        manifest.set("runtime.launcher", self.cli())
        manifest.set("runtime.deployment_dir", str(self.deploy_dir))
        dsn, user = f"127.0.0.1:{DEFAULT_PORT}", "sys"
        try:
            conn = json.loads((self.deploy_dir / "deployment.json").read_text(encoding="utf-8")).get("connection", {})
            dsn = f"{conn.get('host', '127.0.0.1')}:{conn.get('dbPort', DEFAULT_PORT)}"
            user = conn.get("username") or "sys"
        except (OSError, ValueError, AttributeError):
            pass
        manifest.set("runtime.dsn", dsn)
        manifest.set("runtime.user", user)
        warning = None
        try:
            password = json.loads((self.deploy_dir / "secrets.json").read_text(encoding="utf-8")).get("dbPassword", "")
        except (OSError, ValueError, AttributeError):
            password = ""
        if password:
            manifest.set("runtime.password_file", str(credentials.store("personal_sys_password", password)))
        else:
            warning = "Could not read the database password from the Exasol Personal secrets - the exapump profile and AI client configs will ask for it or need manual completion."
        manifest.set("runtime.tls", "self-signed")
        manifest.set("runtime.status", status or self.status().state)
        return warning
