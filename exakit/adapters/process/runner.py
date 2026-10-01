"""Running other programs: the only place ``subprocess`` is imported for tool calls."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Completed:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        """True when the exit code is zero."""
        return self.code == 0


class Runner(Protocol):
    def run(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None,
            timeout: float | None = None, stdin: str | None = None) -> Completed: ...
    def which(self, name: str) -> str | None: ...
    def interactive(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> int: ...
    def spawn(self, cmd: Sequence[str], *, log_path: Path) -> int: ...
    def stream(self, cmd: Sequence[str], on_line: Callable[[str], None], *, env: Mapping[str, str] | None = None,
               timeout: float | None = None) -> Completed: ...


KIT_ROOT = Path(__file__).resolve().parents[3]


def clean_env(base: Mapping[str, str]) -> dict[str, str]:
    """The environment for a child process: the kit's own folder taken out of PYTHONPATH.

    The launcher puts the kit folder on PYTHONPATH so ``python -m exakit`` imports; a child Python (the MCP server
    under uvx, an add-on's venv) would then find the kit's own ``mcp`` package before the MCP SDK and fail to import.
    """
    env = dict(base)
    entries = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and Path(p).resolve() != KIT_ROOT]
    if entries:
        env["PYTHONPATH"] = os.pathsep.join(entries)
    else:
        env.pop("PYTHONPATH", None)
    return env


class SubprocessRunner:
    """Captures both streams, never raises on a non-zero exit, times out with code 124."""

    def run(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None,
            timeout: float | None = None, stdin: str | None = None) -> Completed:
        """Run a command and capture both streams; a timeout answers code 124."""
        full_env = clean_env(os.environ)
        if env:
            full_env.update(env)
        try:
            done = subprocess.run(list(cmd), env=full_env, cwd=str(cwd) if cwd else None, timeout=timeout,
                                  input=stdin, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return Completed(127, "", f"{cmd[0]}: not found")
        except subprocess.TimeoutExpired:
            return Completed(124, "", f"{cmd[0]}: timed out after {timeout}s")
        except OSError as err:
            return Completed(126, "", str(err))
        return Completed(done.returncode, done.stdout, done.stderr)

    def which(self, name: str) -> str | None:
        """The path of a command on PATH, or None."""
        return shutil.which(name)

    def stream(self, cmd: Sequence[str], on_line: Callable[[str], None], *, env: Mapping[str, str] | None = None,
               timeout: float | None = None) -> Completed:
        """Run a long command, handing every line of its merged output to ``on_line`` as it arrives; the lines are also the answer."""
        full_env = clean_env(os.environ)
        if env:
            full_env.update(env)
        try:
            child = subprocess.Popen(list(cmd), env=full_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace")
        except FileNotFoundError:
            return Completed(127, "", f"{cmd[0]}: not found")
        except OSError as err:
            return Completed(126, "", str(err))
        lines: list[str] = []
        deadline = time.monotonic() + timeout if timeout else None
        for raw in child.stdout or []:
            line = raw.rstrip("\n")
            lines.append(line)
            on_line(line)
            if deadline and time.monotonic() > deadline:
                child.kill()
                lines.append(f"{cmd[0]}: timed out after {timeout}s")
                break
        code = child.wait()
        return Completed(code, "\n".join(lines), "")

    def spawn(self, cmd: Sequence[str], *, log_path: Path) -> int:
        """Start a daemon in its own session, both streams appended to ``log_path``; the pid is the answer."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        detached = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with log_path.open("a", encoding="utf-8") as log:
            child = subprocess.Popen(list(cmd), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=clean_env(os.environ), **detached)
        return child.pid

    def interactive(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> int:
        """Run with the terminal attached (a password prompt, a licence screen); the exit code is the answer."""
        full_env = clean_env(os.environ)
        if env:
            full_env.update(env)
        try:
            return subprocess.call(list(cmd), env=full_env)
        except FileNotFoundError:
            return 127
        except OSError:
            return 126
