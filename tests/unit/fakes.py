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
