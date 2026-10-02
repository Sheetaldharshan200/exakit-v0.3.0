"""The list a question shows: a cursor row, a green tick for what is chosen, the terminal's own colours, the mouse as well as the keys."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static

from exakit.ui.menu_rules import tick
from exakit.ui.widgets import Option

ACCENT = "green"
MIN_HINT = 6                                                # the shortest hint worth aligning a column for


def fit(label: str, hint: str, column: int, room: int) -> tuple[str, str]:
    """Cut a row's label and hint to one line of ``room`` cells: the label padded to ``column`` (0 for none), the hint shortened with an ellipsis, dropped when nothing is left for it."""
    if len(label) > room:
        return label[: max(room - 1, 0)] + "…", ""
    label = label.ljust(column) if column else label
    if not hint:
        return label, ""
    left = room - len(label) - 2
    if left >= len(hint):
        return label, hint
    return label, (hint[: left - 1] + "…") if left >= 3 else ""


class ChoiceList(Static, can_focus=True):
    """Rows of options. Up/Down and the mouse move the cursor; Space (or a click) toggles; the screen decides what Enter means."""

    class Chosen(Message):
        """A row was activated with Enter (single choice) or clicked."""

        def __init__(self, index: int, widget: ChoiceList) -> None:
            super().__init__()
            self.index = index
            self.widget = widget

        @property
        def control(self) -> ChoiceList:
            """The list the row belongs to."""
            return self.widget

    class Moved(Message):
        """The cursor moved to a row (the keys, or a click)."""

        def __init__(self, index: int, widget: ChoiceList) -> None:
            super().__init__()
            self.index = index
            self.widget = widget

        @property
        def control(self) -> ChoiceList:
            """The list the row belongs to."""
            return self.widget

    def __init__(self, options: Sequence[Option], *, chosen: Sequence[str] = (), cursor: int = 0, single: bool = False,
                 widget_id: str = "choices", classes: str | None = None, marks: bool = True) -> None:
        super().__init__(id=widget_id, classes=classes)
        self.marks = marks                      # the tick box; a navigation list (the sidebar, an entry list) shows the pointer alone
        self.options = list(options)
        self.chosen: set[str] = {o.id for o in options if o.id in set(chosen) and not o.disabled and not o.heading}
        self.cursor = self._landing(max(0, min(cursor, len(self.options) - 1)))
        self.single = single

    def set_options(self, options: Sequence[Option]) -> None:
        """Replace the rows (a search's results); the cursor returns to the top."""
        self.options = list(options)
        self.chosen = set()
        self.cursor = self._landing(0)
        self.redraw()

    def _landing(self, index: int, step: int = 1) -> int:
        """The first row from ``index`` (in the direction of ``step``, wrapping) that is not a heading."""
        for offset in range(len(self.options)):
            at = (index + offset * step) % len(self.options)
            if not self.options[at].heading:
                return at
        return 0

    def selectable(self) -> list[int]:
        """The rows the cursor can stand on."""
        return [i for i, o in enumerate(self.options) if not o.heading]

    def current(self) -> Option | None:
        """The option under the cursor."""
        return self.options[self.cursor] if self.options else None

    def on_mount(self) -> None:
        """Draw the rows."""
        self.redraw()

    def render(self) -> Text:
        """The rows: pointer, tick box, label, hint. A row is one line whatever the width, so a click's line is its row."""
        text = Text(no_wrap=True, overflow="ellipsis")
        column = max((len(o.label) for o in self.options if o.hint and not o.heading), default=0)
        room = (self.content_size.width or 10_000) - 3 - (2 if self.marks else 0)
        if column + 2 + MIN_HINT > room:
            column = 0                                      # too narrow for aligned columns: the hint follows its label
        for index, option in enumerate(self.options):
            if option.heading:
                text.append(f" {option.label}"[: room + 3], style="bold")
            else:
                self._row(text, option, index, column, room)
            if index < len(self.options) - 1:
                text.append("\n")
        return text

    def _row(self, text: Text, option: Option, index: int, column: int, room: int) -> None:
        """Append one row, cut to the room so it never wraps."""
        current = index == self.cursor
        text.append(f" {'▸' if current else ' '} ", style=ACCENT if current else "")
        if self.marks:
            ticked = option.id in self.chosen
            text.append(("✓" if ticked else ("○" if self.single else "☐")) + " ", style=ACCENT if ticked else "dim")
        label, hint = fit(option.label, option.hint or "", column, room)
        text.append(label, style="dim" if option.disabled else ("bold" if current else ""))
        if hint:
            text.append(f"  {hint}", style="dim")

    def on_resize(self) -> None:
        """A new width: the rows are cut again."""
        self.refresh()

    def redraw(self) -> None:
        """Repaint after a change."""
        self.refresh(layout=True)

    def move(self, delta: int) -> None:
        """Move the cursor, wrapping around."""
        if self.selectable():
            self.cursor = self._landing((self.cursor + delta) % len(self.options), 1 if delta >= 0 else -1)
            self.post_message(self.Moved(self.cursor, self))
        self.redraw()

    def go_to(self, index: int) -> None:
        """Put the cursor on a row."""
        if 0 <= index < len(self.options) and index != self.cursor and not self.options[index].heading:
            self.cursor = index
            self.post_message(self.Moved(index, self))
            self.redraw()

    def toggle(self, index: int | None = None) -> None:
        """Tick or untick a row (the cursor's by default); a single choice moves the tick."""
        index = self.cursor if index is None else index
        if not self.options:
            return
        option = self.options[index]
        if option.disabled or option.heading:
            return
        if self.single:
            self.chosen = {option.id}
        else:
            tick(self.options, self.chosen, index)
        self.cursor = index
        self.redraw()

    def all(self, on: bool) -> None:
        """Tick everything that can be ticked, or nothing."""
        self.chosen = {o.id for o in self.options if not o.disabled and not o.heading} if on else set()
        self.redraw()

    def on_key(self, event: events.Key) -> None:
        """Up/Down (and j/k) move; Space toggles; a digit picks that row."""
        if event.key in ("up", "k"):
            self.move(-1)
        elif event.key in ("down", "j"):
            self.move(1)
        elif event.key == "space":
            self.toggle()
        elif event.key == "enter" and self.single and self.options:
            self.post_message(self.Chosen(self.cursor, self))
        elif event.character and event.character.isdigit() and 1 <= int(event.character) <= len(self.selectable()):
            index = self.selectable()[int(event.character) - 1]          # the nth row a cursor can stand on
            self.toggle(index)
            if self.single:
                self.post_message(self.Chosen(index, self))
        else:
            return
        event.stop()

    def on_click(self, event: events.Click) -> None:
        """A click on a row toggles it (and chooses it, in a single choice)."""
        offset = event.get_content_offset(self)        # relative to the rows, whatever border or padding the list has
        index = offset.y if offset is not None else -1
        if 0 <= index < len(self.options) and not self.options[index].heading:
            self.toggle(index)
            self.post_message(self.Moved(index, self))
            if self.single:
                self.post_message(self.Chosen(index, self))
            event.stop()
