"""A block of facts: free lines and key/value rows, wrapped at render time so a long value stays in its column."""

from __future__ import annotations

import textwrap
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

KEY_WIDTH = 18


class Facts:
    """Lines (with a style) and key/value rows, rendered to the width Rich gives: a value wraps under itself, never under its key."""

    def __init__(self) -> None:
        self.parts: list[tuple[str, str, str | None]] = []       # ("line", text, style) or ("kv", key, value)

    def line(self, text: str, style: str | None = None) -> Facts:
        """A free line (may hold newlines)."""
        self.parts.append(("line", text, style))
        return self

    def kv(self, key: str, value: Any) -> Facts:
        """A key/value row."""
        self.parts.append(("kv", key, str(value)))
        return self

    @property
    def plain(self) -> str:
        """The text without styles, one row per line, for tests and the transcript."""
        return "".join(text if kind == "line" else f"{text:<{KEY_WIDTH}}{value}\n" for kind, text, value in self.parts)

    def __str__(self) -> str:
        return self.plain

    def render(self, width: int) -> Text:
        """The block at ``width`` columns."""
        out = Text()
        room = max(10, width - KEY_WIDTH)
        for kind, text, value in self.parts:
            if kind == "line":
                out.append(text, style=value)
                continue
            lines = textwrap.wrap(value or "-", room, break_long_words=True, break_on_hyphens=False) or ["-"]
            out.append(f"{text:<{KEY_WIDTH}}", style="dim").append(lines[0] + "\n")
            for rest in lines[1:]:
                out.append(" " * KEY_WIDTH + rest + "\n")
        return out

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Rich asks with the width it has."""
        yield self.render(options.max_width)
