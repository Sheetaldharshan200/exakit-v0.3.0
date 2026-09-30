"""exapump: the kit's SQL and bulk-load CLI, and the profile file it reads.

The kit never runs ``exapump profile``; it writes ``~/.exapump/config.toml``
itself. SQL goes to exapump on stdin, never on a command line, and a password
travels in the environment.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from exakit.domain.errors import Failed

from .fs.atomic import atomic_write_text
from .process.runner import Completed, Runner

DEFAULT_PROFILE = "starter-kit"
LISTING_SQL = ("SELECT 'EXAKIT.LISTING_ANSWERED|1' AS QUALIFIED FROM DUAL UNION ALL "
               "SELECT TABLE_SCHEMA || '.' || TABLE_NAME || '|' || TABLE_ROW_COUNT FROM SYS.EXA_ALL_TABLES")
_LISTING_LINE = re.compile(r"^[A-Za-z0-9_$]+\.[A-Za-z0-9_$]+\|[0-9]+$")


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    host: str
    port: int
    user: str
    password: str
    schema: str | None = None

    def toml(self) -> str:
        lines = [f"[{self.name}]", f'host = "{_toml(self.host)}"', f"port = {self.port}",
                 f'user = "{_toml(self.user)}"', f'password = "{_toml(self.password)}"']
        if self.schema:
            lines.append(f'schema = "{_toml(self.schema)}"')
        lines += ["tls = true", "validate_certificate = false"]
        return "\n".join(lines) + "\n"


def _toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_profile(config_path: Path, profile: Profile) -> None:
    """Replace or append the profile's section in the TOML file; atomic, mode 0600."""
    text = ""
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
    section = profile.toml()
    pattern = re.compile(rf"\[{re.escape(profile.name)}\][^\[]*", re.S)
    if pattern.search(text):
        text = pattern.sub(section.replace("\\", "\\\\"), text, count=1)
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + section
    atomic_write_text(config_path, text, mode=0o600)


class Exapump(Protocol):
    bin: str
    def sql(self, profile: str, text: str, *, config: Path | None = None, json_rows: bool = False, timeout: float = 600) -> Completed: ...
    def sql_file(self, profile: str, path: Path, *, timeout: float = 3600) -> Completed: ...
    def upload(self, file: Path, table: str, profile: str, *, delimiter: str | None = None, timeout: float = 3600) -> Completed: ...
    def version(self) -> str | None: ...


class ExapumpCli:
    """The real binary. ``config`` overrides EXAPUMP_CONFIG for one call (a temp file with extra profiles)."""

    def __init__(self, bin: str, runner: Runner, *, config_path: Path | None = None) -> None:
        self.bin = bin
        self.runner = runner
        self.config_path = config_path

    def _env(self, config: Path | None) -> dict[str, str]:
        env = {}
        path = config or self.config_path
        if path:
            env["EXAPUMP_CONFIG"] = str(path)
        return env

    def sql(self, profile: str, text: str, *, config: Path | None = None, json_rows: bool = False, timeout: float = 600) -> Completed:
        cmd = [self.bin, "sql", "-p", profile]
        if json_rows:
            cmd += ["-f", "json"]
        return self.runner.run(cmd, stdin=text.rstrip("\n") + "\n", env=self._env(config), timeout=timeout)

    def sql_file(self, profile: str, path: Path, *, timeout: float = 3600) -> Completed:
        return self.runner.run([self.bin, "sql", "-p", profile], stdin=path.read_text(encoding="utf-8"),
                               env=self._env(None), timeout=timeout)

    def upload(self, file: Path, table: str, profile: str, *, delimiter: str | None = None, timeout: float = 3600) -> Completed:
        cmd = [self.bin, "upload", str(file), "--table", table, "-p", profile]
        if delimiter and delimiter != ",":
            cmd += ["--delimiter", delimiter]
        return self.runner.run(cmd, env=self._env(None), timeout=timeout)

    def version(self) -> str | None:
        done = self.runner.run([self.bin, "--version"], timeout=10)
        match = re.search(r"[0-9]+\.[0-9]+[0-9A-Za-z._+-]*", done.out.splitlines()[0] if done.out else "")
        return match.group(0) if done.ok and match else None


@contextmanager
def temp_config(directory: Path, profiles: list[Profile]) -> Iterator[Path]:
    """A throwaway config carrying extra profiles (the MCP read-only user); removed afterwards."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f".exapump-{os.getpid()}.toml"
    atomic_write_text(path, "".join(p.toml() + "\n" for p in profiles), mode=0o600)
    try:
        yield path
    finally:
        try:
            path.unlink()
        except OSError:
            pass


# --- parsing the answers the kit relies on ---------------------------------------


def has_token(done: Completed, token: str) -> bool:
    return done.ok and token in done.out


def table_listing(done: Completed) -> dict[str, int] | None:
    """``SCHEMA.TABLE`` -> rows from the listing query; None when the database did not answer."""
    if not done.ok or "EXAKIT.LISTING_ANSWERED|1" not in done.out:
        return None
    rows: dict[str, int] = {}
    for line in done.out.splitlines():
        line = line.strip()
        if _LISTING_LINE.match(line) and not line.startswith("EXAKIT.LISTING_ANSWERED|"):
            name, count = line.rsplit("|", 1)
            rows[name.upper()] = int(count)
    return rows


def failure_reason(log_tail: str, *, delimiter_name: str = "comma", crlf: bool = False) -> str:
    """The one line that explains a failed upload, from exapump's last ``Error:`` line."""
    errors = [l for l in log_tail.splitlines() if l.startswith("Error: ")]
    if not errors:
        return "exapump did not say why (see the log)"
    line = re.sub(r"\{[^}]*\}", "<JSON value>", errors[-1])
    row = re.search(r"row=(\d+)", line)
    where = f"row {row.group(1)}" if row else "a row"
    if "not enclosed field" in line:
        return f"{where} has a line break or an unescaped {delimiter_name} inside a quoted field"
    if "<CR>" in line:
        return "the file has Windows line endings inside quoted fields; convert it to LF"
    match = re.search(r"(ETL-\d+: .*)", line)
    text = match.group(1) if match else line[len("Error: "):]
    text = re.sub(r"\s*\(Session: [^)]*\)", "", text)
    if len(text) > 160:
        text = text[:160].rsplit(" ", 1)[0] + "..."
    if crlf:
        text += " - the file has Windows line endings"
    return text


def looks_not_runnable_yet(text: str) -> bool:
    """A binary a virus scanner still holds (the Windows Defender hold on new files)."""
    return any(s in text for s in ("Access is denied", "failed to run", "being used by another process",
                                    "Text file busy", "cannot access the file", "contains a virus"))
