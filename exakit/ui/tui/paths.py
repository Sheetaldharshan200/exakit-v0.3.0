"""Path completion for the screens: what Tab fills in is exactly the ghost text, and both come from here."""

from __future__ import annotations

from pathlib import Path

from textual.suggester import Suggester


def complete_path(value: str, home: Path | None = None) -> str | None:
    """``value`` extended by the first entry its last part starts with (folders end in /), as typed - ``~`` stays ``~``.

    None when nothing on disk extends it. Hidden entries are offered only once a dot is typed. Case is ignored
    in the match (macOS and Windows folders are), and the entry's own spelling is what is filled in.
    """
    if not value or value.endswith(("/.", "/..")):
        return None
    home = home or Path.home()
    expanded = str(home) + value[1:] if value == "~" or value.startswith("~/") else value
    folder, _, prefix = expanded.rpartition("/")
    base = Path(folder or ("/" if expanded.startswith("/") else "."))
    if value == "~":
        return "~/"
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    for entry in entries:
        if entry.name.startswith(".") and not prefix.startswith("."):
            continue
        if entry.name.lower().startswith(prefix.lower()) and entry.name != prefix:
            suffix = entry.name[len(prefix):] + ("/" if entry.is_dir() else "")
            return value[: len(value) - len(prefix)] + entry.name[: len(prefix)] + suffix if prefix else value + suffix
    return None


class PathSuggester(Suggester):
    """The ghost text: the completion Tab would make."""

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        """The completed path when it extends what was typed (ghost text can only extend the text)."""
        found = complete_path(value)
        return found if found and found.lower().startswith(value.lower()) and found != value else None
