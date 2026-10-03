"""The dashboard's search: an input that completes inline (the ghost text is exactly what Tab fills in) and lists the matches as you type."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.suggester import Suggester
from textual.widgets import Input

from exakit.ui.widgets import Option

from .choices import ChoiceList
from .panels import Loader


class FirstMatch(Suggester):
    """The ghost text in the search input: the first match's name, the very thing Tab fills in."""

    def __init__(self, bar: SearchBar) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self.bar = bar

    async def get_suggestion(self, value: str) -> str | None:
        """The first match when it begins with what was typed (ghost text can only extend the text)."""
        found = self.bar.matches(value)
        if found and found[0][1].lower().startswith(value.lower()):
            return found[0][1]
        return None


class SearchBar(Vertical):
    """An input that completes inline (Tab accepts) and lists the matches as you type; Enter opens the best one."""

    def __init__(self) -> None:
        super().__init__(id="search")
        self.entries: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        """The input and the results list."""
        with Horizontal(id="search-row"):
            yield Input(placeholder="Search commands and components   (Tab completes, Enter opens, / focuses)", id="search-input", suggester=FirstMatch(self))
            yield Loader()
        yield ChoiceList([], single=True, widget_id="results", classes="hidden", marks=False)

    @property
    def results(self) -> ChoiceList:
        """The results list."""
        return self.query_one("#results", ChoiceList)

    def set_entries(self, entries: list[tuple[str, str, str]]) -> None:
        """The searchable entries; the inline completion knows their ids and labels."""
        self.entries = [e for e in entries if e[0] != "section"]

    def matches(self, query: str) -> list[tuple[str, str, str]]:
        """The entries whose id or label contains the text, ids first."""
        q = query.strip().lower()
        if not q:
            return []
        starts = [e for e in self.entries if e[1].lower().startswith(q)]
        rest = [e for e in self.entries if e not in starts and (q in e[1].lower() or q in e[2].lower())]
        return (starts + rest)[:8]

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh the results list."""
        found = self.matches(event.value)
        self.results.set_options([Option(f"{e[0]}:{e[1]}", e[1], hint=e[2]) for e in found])
        self.results.set_class(not found, "hidden")

    def _open(self, option_id: str) -> None:
        kind, ident = option_id.split(":", 1)
        self.app.call_later(self.app.open_entry, kind, ident)     # type: ignore[attr-defined]
        self.query_one(Input).value = ""
        self.results.set_class(True, "hidden")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the input opens the best match."""
        found = self.matches(event.value)
        if found:
            self._open(f"{found[0][0]}:{found[0][1]}")

    def on_choice_list_chosen(self, event: ChoiceList.Chosen) -> None:
        """A clicked result opens."""
        option = self.results.options[event.index]
        self._open(option.id)

    def complete(self) -> None:
        """Tab fills the input with the first match's name."""
        field = self.query_one(Input)
        found = self.matches(field.value)
        if found:
            field.value = found[0][1]
            field.cursor_position = len(field.value)

    def on_key(self, event) -> None:
        """Tab completes; Down moves from the input into the results; Enter in the results opens; Up at the top returns."""
        field = self.query_one(Input)
        listed = not self.results.has_class("hidden")
        if event.key == "tab" and field.has_focus:
            self.complete()
        elif event.key == "down" and field.has_focus and listed:
            self.results.focus()
        elif event.key == "enter" and self.results.has_focus and self.results.current() is not None:
            self._open(self.results.current().id)
        elif event.key == "up" and self.results.has_focus and self.results.cursor == 0:
            field.focus()
        else:
            return
        event.stop()
        event.prevent_default()
