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
