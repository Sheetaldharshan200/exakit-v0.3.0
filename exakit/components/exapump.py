"""exapump: the SQL and bulk-load CLI. A verified release binary in the bin dir plus the ``starter-kit`` profile."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from exakit.adapters.exapump import Profile, looks_not_runnable_yet, write_profile
from exakit.adapters.net.github import download_url
from exakit.domain.errors import Failed
from exakit.lifecycles.base import temp_dir

from .base import ComponentBase

REPO = "exasol-labs/exapump"
PINNED = {
    "exapump-0.11.2-linux-aarch64": "106c3c5ea168a1381549807b82639137c8b3f94bd64c1b6d02fa380a025d5085",
    "exapump-0.11.2-linux-x86_64": "669af4d488e5b1ae2e9c9e030c1be4b1cdb7442dedf3175a361928613f4b3e80",
    "exapump-0.11.2-macos-aarch64": "e1438c69f26cdcca69ad1b7211aa9495524c53ff1badebee91d5a631c503616b",
    "exapump-0.11.2-macos-x86_64": "1dd68d2dbc2d556e1613975eeffb25813f1ec60e06e93d514d5dd86df8144648",
}
VERSION_IN_TEXT = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class Lifecycle(ComponentBase):
    id = "exapump"
    key = "exapump"
    step = "exapump"

    @property
    def bin(self) -> Path:
        return self.ctx.paths.bin_dir / ("exapump.exe" if self.ctx.platform.os == "windows" else "exapump")

    @property
    def config_path(self) -> Path:
        base = self.ctx.env.get("EXAKIT_EXAPUMP_CONFIG_DIR") or str(Path(self.ctx.env.get("HOME") or Path.home()) / ".exapump")
        return Path(base) / "config.toml"

    @property
    def profile(self) -> str:
        return self.ctx.env.get("EXAKIT_EXAPUMP_PROFILE") or "starter-kit"

    def cli(self) -> str:
        if self.bin.exists():
            return str(self.bin)
        return self.ctx.runner.which("exapump") or str(self.bin)

    def live_version(self, path: str | None = None) -> str | None:
        done = self.ctx.runner.run([path or self.cli(), "--version"], timeout=10)
        match = VERSION_IN_TEXT.search(done.out.splitlines()[0] if done.ok and done.out else "")
        return match.group(0) if match else None

    def installed_version(self) -> str | None:
        return self.live_version() if Path(self.cli()).exists() else None

    # --- install ---------------------------------------------------------------------------

    def asset_name(self, version: str) -> str:
        suffix = ".exe" if self.ctx.platform.os == "windows" else ""
        return f"exapump-{version}-{self.ctx.platform.platform_key}{suffix}"

    def digest_for(self, version: str, asset: str) -> str | None:
        published = self.published_digest(version, self.ctx.platform.platform_key)
        return published or PINNED.get(asset)

    def _keep_existing(self, version: str) -> bool:
        """True when a working exapump of the right version is already in place (and recorded)."""
        if self.force() or not Path(self.cli()).exists():
            return False
        have = self.live_version()
        if have is None:
            if self.cli() == str(self.bin):
                self.ctx.ui.warn("Existing exapump binary does not run (interrupted download?) - reinstalling")
                self.bin.unlink(missing_ok=True)
            return False
        if have != version and self.cli() == str(self.bin):
            self.ctx.ui.info(f"exapump {have} is installed; this kit ships {version} - replacing it")
            self.bin.unlink(missing_ok=True)
            return False
        self.ctx.ui.ok(f"exapump already installed: {self.cli()}")
        self.record(version=have, path=self.cli())
        return True

    def install(self, version: str) -> None:
        if self.ctx.platform.arch not in ("aarch64", "x86_64"):
            raise Failed(f"Unsupported CPU architecture: {self.ctx.platform.arch}. exapump binaries exist for x86_64 and arm64 only.")
        if self._keep_existing(version):
            return
        asset = self.asset_name(version)
        started = time.monotonic()
        self.ctx.ui.info(f"Downloading exapump v{version} ({asset})")
        with temp_dir("exakit-exapump-") as tmp:
            staged = Path(tmp) / asset
            self.fetch_verified(download_url(REPO, f"v{version}", asset), staged, digest=self.digest_for(version, asset), what=asset,
                                repo=REPO, tag=f"v{version}", asset=asset)
            self.install_binary(staged, self.bin)
        self.verify_runs()
        self.ctx.ui.ok(f"exapump v{version} installed to {self.bin} ({self.elapsed(started)})")
        self.record(version=version, path=str(self.bin))

    def verify_runs(self) -> None:
        """Wait out a virus scanner holding the new binary; then it must answer --version."""
        budget = int(self.ctx.env.get("EXAKIT_EXAPUMP_READY_TIMEOUT") or 180)
        started = time.monotonic()
        said = False
        while True:
            done = self.ctx.runner.run([str(self.bin), "--version"], timeout=10)
            if done.ok:
                return
            text = done.err + done.out
            if not looks_not_runnable_yet(text) or time.monotonic() - started >= budget:
                break
            if not said:
                self.ctx.ui.info(f"The new exapump cannot start yet (a virus scanner still holds it) - waiting up to {budget}s")
                said = True
            time.sleep(5)
        self.ctx.log.line("ERR", f"exapump --version failed (rc={done.code}): {text.strip()[-300:]}")
        if looks_not_runnable_yet(text):
            raise Failed(f"exapump was installed and verified, but this machine will not let it run: {text.strip().splitlines()[0] if text.strip() else 'no output'}. "
                         f"A virus scanner or endpoint-security agent is holding it. Allow {self.bin} (or wait for the scan to finish), then: exakit update",
                         remedy="exakit update exapump")
        if "GLIBC_" in text:
            raise Failed("exapump's release binary needs a newer glibc than this system has. The container shim the legacy installer "
                         "builds for this case is not part of the Python kit yet - re-run the installer to get it.", remedy=self.ctx.install_command())
        raise Failed(f"exapump was installed but does not run: {text.strip() or 'unknown error'}. See the log and https://github.com/{REPO}/issues")

    # --- the profile and the check --------------------------------------------------------------

    def create_profile(self) -> None:
        host, port, user, pw_file = self.runtime_connection()
        if not host or not port:
            raise Failed("No runtime DSN in the manifest - install the database first.", remedy=self.ctx.install_command())
        password = self.password(pw_file)
        if not password:
            self.ctx.ui.warn(f"No database password available - create the profile manually with: exapump profile init {self.profile}")
            return
        write_profile(self.config_path, Profile(self.profile, host, port, user, password))
        self.record(profile=self.profile)
        self.ctx.ui.ok(f"Connection profile [{self.profile}] written to {self.config_path}")

    def validate(self) -> None:
        if not self.recorded("profile"):
            raise Failed(f"No connection profile exists (no database password was available to write one). Create it manually with "
                         f"'exapump profile init {self.profile}', then re-run.")
        self.ctx.ui.info("Validating the database connection (SELECT 1)")
        for attempt in range(6):
            if self.ctx.runner.run([self.cli(), "sql", "-p", self.profile, "SELECT 1"], timeout=120).ok:
                self.ctx.ui.ok("Connection works")
                self.record(validated=True)
                return
            if attempt < 5:
                time.sleep(5)
        raise Failed(f"SELECT 1 failed via profile '{self.profile}'. Try: exapump sql -p {self.profile} 'SELECT 1'")

    # --- update and uninstall ----------------------------------------------------------------------

    def update(self, options: list[str] | None = None) -> None:
        latest = self.target_version()
        current = self.installed_version()
        recorded = self.recorded("version")
        if latest == current:
            if recorded != current:
                self.ctx.ui.info(f"Reconciling the recorded exapump version ({recorded or 'unrecorded'}) with the binary on disk")
                self.record(version=current)
            self.ctx.ui.ok(f"exapump is already current ({current})")
            return
        self.ctx.ui.info(f"Updating exapump {current or 'not installed'} -> {latest}")
        self.ctx.env = {**dict(self.ctx.env), "EXAKIT_FORCE_COMPONENT_INSTALL": "1"}
        self.install(latest)
        self.create_profile()
        self.record_desired(latest)
        live = self.installed_version()
        if live and live != latest:
            self.ctx.ui.warn(f"The exapump on disk reports {live}, not the {latest} this update installed - recording what is there")
            self.record(version=live)
            return
        self.ctx.ui.ok("exapump updated without changing database data")

    def uninstall(self, *, dry_run: bool) -> list[str]:
        targets = [self.bin, self.config_path.parent, self.ctx.paths.home / "libexec"]
        if dry_run:
            self.ctx.ui.info(f"  will remove: exapump ({self.bin} and the profiles at {self.config_path.parent})")
            return [str(t) for t in targets if t.exists()]
        self.ctx.ui.info("Removing exapump and its profiles")
        removed = []
        for target in targets:
            if target.exists():
                removed.append(str(target))
                shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
        self.forget()
        return removed
