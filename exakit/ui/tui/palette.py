"""The kit's entries in the command palette (Ctrl-P): the sections, every command, every component and add-on."""

from __future__ import annotations

from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider


class KitProvider(Provider):
    """Searches the dashboard's entries; choosing one opens it."""

    @property
    def entries(self) -> list[tuple[str, str, str]]:
        """(kind, id, label) from the app."""
        entries = getattr(self.app, "entries", None)
        return list(entries()) if callable(entries) else []

    async def discover(self) -> Hits:
        """With nothing typed: the sections."""
        for kind, ident, label in self.entries:
            if kind == "section":
                yield DiscoveryHit(label, partial(self.app.call_later, self.app.open_entry, kind, ident), help="Open this section")

    async def search(self, query: str) -> Hits:
        """Whatever matches the typed text."""
        matcher = self.matcher(query)
        for kind, ident, label in self.entries:
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, matcher.highlight(label), partial(self.app.call_later, self.app.open_entry, kind, ident), help={"command": "Show the command", "item": "Show the component", "section": "Open the section"}.get(kind, ""))
