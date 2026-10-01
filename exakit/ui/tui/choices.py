"""The list a question shows: a cursor row, a green tick for what is chosen, the terminal's own colours, the mouse as well as the keys."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static

from exakit.ui.widgets import Option

ACCENT = "green"


class ChoiceList(Static, can_focus=True):
    """Rows of options. Up/Down and the mouse move the cursor; Space (or a click) toggles; the screen decides what Enter means."""

    class Chosen(Message):
        """A row was activated with Enter (single choice) or clicked."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, options: Sequence[Option], *, chosen: Sequence[str] = (), cursor: int = 0, single: bool = False) -> None:
        super().__init__(id="choices")
        self.options = list(options)
        self.chosen: set[str] = {o.id for o in options if o.id in set(chosen) and not o.disabled}
        self.cursor = max(0, min(cursor, len(self.options) - 1))
        self.single = single

    def on_mount(self) -> None:
        """Draw the rows."""
        self.redraw()

    def render(self) -> Text:
        """The rows: pointer, tick box, label, hint."""
        text = Text()
        for index, option in enumerate(self.options):
            pointer = "▸" if index == self.cursor else " "
            ticked = option.id in self.chosen
            mark = "✓" if ticked else ("○" if self.single else "☐")
            text.append(f" {pointer} ", style=ACCENT if index == self.cursor else "")
            text.append(mark + " ", style=ACCENT if ticked else "dim")
            text.append(option.label, style=("dim" if option.disabled else ("bold" if index == self.cursor else "")))
            if option.hint:
                text.append(f"  {option.hint}", style="dim")
            if index < len(self.options) - 1:
                text.append("\n")
        return text

    def redraw(self) -> None:
        """Repaint after a change."""
        self.refresh(layout=True)

    def move(self, delta: int) -> None:
        """Move the cursor, wrapping around."""
        self.cursor = (self.cursor + delta) % len(self.options)
        self.redraw()

    def toggle(self, index: int | None = None) -> None:
        """Tick or untick a row (the cursor's by default); a single choice moves the tick."""
        index = self.cursor if index is None else index
        option = self.options[index]
        if option.disabled:
            return
        if self.single:
            self.chosen = {option.id}
        else:
            self.chosen ^= {option.id}
        self.cursor = index
        self.redraw()

    def all(self, on: bool) -> None:
        """Tick everything that can be ticked, or nothing."""
        self.chosen = {o.id for o in self.options if not o.disabled} if on else set()
        self.redraw()

    def on_key(self, event: events.Key) -> None:
        """Up/Down (and j/k) move; Space toggles; a digit picks that row."""
        if event.key in ("up", "k"):
            self.move(-1)
        elif event.key in ("down", "j"):
            self.move(1)
        elif event.key == "space":
            self.toggle()
        elif event.character and event.character.isdigit() and 1 <= int(event.character) <= len(self.options):
            self.toggle(int(event.character) - 1)
            if self.single:
                self.post_message(self.Chosen(int(event.character) - 1))
        else:
            return
        event.stop()

    def on_click(self, event: events.Click) -> None:
        """A click on a row toggles it (and chooses it, in a single choice)."""
        index = event.y
        if 0 <= index < len(self.options):
            self.toggle(index)
            if self.single:
                self.post_message(self.Chosen(index))
            event.stop()
