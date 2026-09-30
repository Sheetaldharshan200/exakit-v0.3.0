"""Fakes for the adapter Protocols. Tests inject these; nothing here touches the network or the machine."""

from __future__ import annotations

from pathlib import Path

from exakit.domain.errors import Failed


class FakeDownloader:
    """Answers ``text()`` from a dict of url -> body; a url that is absent raises like a network error."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = dict(pages or {})
        self.calls: list[str] = []

    def text(self, url: str, *, token: str | None = None) -> str:
        self.calls.append(url)
        if url not in self.pages:
            raise Failed(f"Could not download {url}.")
        return self.pages[url]

    def fetch(self, url: str, dest: Path, *, sha256: str | None = None, token: str | None = None, what: str = "file") -> Path:
        self.calls.append(url)
        if url not in self.pages:
            raise Failed(f"Could not download {url}.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.pages[url])
        return dest


class ListLog:
    """Collects log lines in memory."""

    path = None

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def line(self, level: str, message: str) -> None:
        self.lines.append((level, message))


class FakeRunner:
    """Answers commands from a table keyed by the leading argv words; records every call."""

    def __init__(self, responses: dict[tuple[str, ...], "Completed"] | None = None, which: dict[str, str] | None = None) -> None:
        from exakit.adapters.process.runner import Completed
        self._default = Completed(0, "", "")
        self.responses = dict(responses or {})
        self.which_table = dict(which or {})
        self.calls: list[tuple[str, ...]] = []

    def run(self, cmd, *, env=None, cwd=None, timeout=None, stdin=None):
        self.calls.append(tuple(cmd))
        best = None
        for key, value in self.responses.items():
            if tuple(cmd[: len(key)]) == key and (best is None or len(key) > len(best)):
                best = key
        return self.responses[best] if best is not None else self._default

    def which(self, name: str):
        return self.which_table.get(name)


class FakeClientOps:
    """Canned documents per verb; records every call."""

    def __init__(self, docs: dict[str, dict] | None = None, codes: dict[str, int] | None = None) -> None:
        from exakit.adapters.clients import ClientCall
        self._ClientCall = ClientCall
        self.docs = dict(docs or {})
        self.codes = dict(codes or {})
        self.calls: list[tuple] = []

    def _answer(self, verb: str):
        return self._ClientCall(self.codes.get(verb, 0), self.docs.get(verb), "")

    def discover(self, runtime_root):
        self.calls.append(("discover",))
        return self._answer("discover")

    def setup(self, runtime_root, clients):
        self.calls.append(("setup", tuple(clients)))
        return self._answer("setup")

    def operation(self, op, runtime_root, clients, *, servers=None):
        self.calls.append((op, tuple(clients), tuple(servers or ())))
        return self._answer(op)

    def register_addon_servers(self, runtime_root, clients):
        self.calls.append(("register", tuple(clients)))
        return self._answer("register")


class FakeExapump:
    """Answers SQL by substring rules: the first rule whose needle is in the statement wins."""

    def __init__(self, rules: list[tuple[str, "Completed"]] | None = None, default=None, bin: str = "/fake/exapump") -> None:
        from exakit.adapters.process.runner import Completed
        self.bin = bin
        self.rules = list(rules or [])
        self.default = default or Completed(0, "", "")
        self.calls: list[tuple[str, str]] = []
        self.uploads: list[tuple] = []

    def sql(self, profile, text, *, config=None, json_rows=False, timeout=600):
        self.calls.append((profile, text))
        for needle, answer in self.rules:
            if needle in text:
                return answer
        return self.default

    def sql_file(self, profile, path, *, timeout=3600):
        return self.sql(profile, path.read_text())

    def upload(self, file, table, profile, *, delimiter=None, timeout=3600):
        self.uploads.append((str(file), table, profile, delimiter))
        return self.default

    def version(self):
        return "0.13.0"


class FakeRuntime:
    def __init__(self, state: str = "running", port: int = 8563, exists: bool = True) -> None:
        from exakit.adapters.runtime.personal import RuntimeStatus
        self._status = RuntimeStatus(state, port)
        self._exists = exists
        self.started = 0
        self.stopped = 0
        self.reap_ok = False

    def status(self):
        return self._status

    def running(self):
        return self._status.state == "running"

    def deployment_exists(self):
        return self._exists

    def start(self, say):
        self.started += 1
        self._status = self._status.__class__("running", self._status.port)

    def stop(self, say):
        self.stopped += 1
        self._status = self._status.__class__("stopped", self._status.port)

    def wait_ready(self, say, *, budget=None):
        return self.running()

    def wait_ready_or_deploy(self, say):
        return self.running()

    def deploy(self, say):
        self._exists = True
        self._status = self._status.__class__("running", self._status.port)

    def db_port(self):
        return self._status.port

    def wedged(self):
        return None

    def cli(self):
        return "/fake/bin/exasol"

    def reap_orphan(self, port, say):
        self.reaped = getattr(self, "reaped", 0) + 1
        if self.reap_ok:
            self._status = self._status.__class__("stopped", self._status.port)
        return self.reap_ok
