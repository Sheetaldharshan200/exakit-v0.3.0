"""The modal questions of the kit's screens: a single choice, a tick list, a yes/no, a line of text.

The keys match the console menus: Up/Down move, Space ticks, Enter continues, a digit picks,
``a``/``n`` take all or none, Esc backs out with the default. The mouse ticks and chooses too.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from exakit.ui.widgets import Option

from .choices import ChoiceList
from .paths import PathSuggester, complete_path


class SelectScreen(ModalScreen[str | None]):
    """One choice out of a list; the answer is the option's id, None when backed out."""

    BINDINGS = [Binding("enter", "done", "Choose", priority=True), Binding("escape", "cancel", "Back")]

    def __init__(self, title: str, options: Sequence[Option], default: int) -> None:
        super().__init__()
        self.title_text = title
        self.options = list(options)
        self.default = default

    def compose(self) -> ComposeResult:
        """The title, the list, the key hint."""
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="title")
            cursor = self.default - 1 if 1 <= self.default <= len(self.options) else 0
            yield ChoiceList(self.options, chosen=[self.options[cursor].id] if self.options else [], cursor=cursor, single=True)
            yield Label("Up/Down or the mouse   Enter chooses   a digit picks   Esc backs out", id="hint")

    def on_mount(self) -> None:
        """Focus the list."""
        self.query_one(ChoiceList).focus()

    def on_choice_list_chosen(self, event: ChoiceList.Chosen) -> None:
        """A click or a digit answers at once."""
        self.dismiss(self.options[event.index].id)

    def action_done(self) -> None:
        """Enter answers with the cursor's row."""
        choices = self.query_one(ChoiceList)
        option = choices.options[choices.cursor]
        if not option.disabled:
            self.dismiss(option.id)

    def action_cancel(self) -> None:
        """Esc: no answer."""
        self.dismiss(None)


class CheckboxScreen(ModalScreen[list[str]]):
    """Any number of choices; the answer is the ticked ids in the list's order."""

    BINDINGS = [Binding("enter", "done", "Continue", priority=True), Binding("escape", "cancel", "Back"),
                Binding("a", "all", "All", show=False), Binding("n", "none", "None", show=False)]

    def __init__(self, title: str, options: Sequence[Option], defaults: Sequence[str]) -> None:
        super().__init__()
        self.title_text = title
        self.options = list(options)
        self.defaults = [o.id for o in options if o.id in set(defaults) and not o.disabled]

    def compose(self) -> ComposeResult:
        """The title, the tick list, the key hint."""
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="title")
            yield ChoiceList(self.options, chosen=self.defaults)
            yield Label("Up/Down or the mouse   Space or a click ticks   Enter continues   a all   n none   Esc backs out", id="hint")

    def on_mount(self) -> None:
        """Focus the list."""
        self.query_one(ChoiceList).focus()

    def action_done(self) -> None:
        """Enter: the ticked ids, in the list's order."""
        ticked = self.query_one(ChoiceList).chosen
        self.dismiss([o.id for o in self.options if o.id in ticked])

    def action_all(self) -> None:
        """Tick everything that can be ticked."""
        self.query_one(ChoiceList).all(True)

    def action_none(self) -> None:
        """Untick everything."""
        self.query_one(ChoiceList).all(False)

    def action_cancel(self) -> None:
        """Esc: the defaults."""
        self.dismiss(list(self.defaults))


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question; Enter takes the default, y and n answer directly."""

    BINDINGS = [Binding("y", "yes", "Yes", show=False), Binding("n", "no", "No", show=False),
                Binding("enter", "default", "Default", priority=True), Binding("escape", "default", "Back")]

    def __init__(self, question: str, default: bool) -> None:
        super().__init__()
        self.question = question
        self.default = default

    def compose(self) -> ComposeResult:
        """The question and the two buttons."""
        with Vertical(id="dialog"):
            yield Label(self.question, id="title")
            with Horizontal(id="buttons"):
                yield Button("Yes", id="yes", variant="primary" if self.default else "default")
                yield Button("No", id="no", variant="primary" if not self.default else "default")
            yield Label(f"Enter takes {'yes' if self.default else 'no'}   y / n answer   Esc backs out", id="hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """A click answers."""
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        """y."""
        self.dismiss(True)

    def action_no(self) -> None:
        """n."""
        self.dismiss(False)

    def action_default(self) -> None:
        """Enter or Esc: the default."""
        self.dismiss(self.default)


class PromptScreen(ModalScreen[str]):
    """A line of text; an empty answer is the default."""

    BINDINGS = [Binding("escape", "cancel", "Back")]

    def __init__(self, question: str, default: str) -> None:
        super().__init__()
        self.question = question
        self.default = default

    def compose(self) -> ComposeResult:
        """The question and the field."""
        with Vertical(id="dialog"):
            yield Label(self.question, id="title")
            yield Input(value=self.default, id="answer")
            yield Label("Enter continues   Esc keeps the default", id="hint")

    def on_mount(self) -> None:
        """Focus the field."""
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter answers with the text, or the default when empty."""
        self.dismiss(event.value.strip() or self.default)

    def action_cancel(self) -> None:
        """Esc: the default."""
        self.dismiss(self.default)


class PathScreen(ModalScreen[str | None]):
    """A file or folder to load: a field as wide as the terminal allows, Tab completing from the disk, the path checked
    before the box closes. None when the user went back."""

    BINDINGS = [Binding("escape", "cancel", "Back"), Binding("tab", "complete", "Complete", show=False, priority=True)]

    def __init__(self, title: str, default: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.default = default

    def compose(self) -> ComposeResult:
        """The title, what can be loaded, the field, the problem line and the keys."""
        with Vertical(id="path-dialog"):
            yield Label(self.title_text, id="title")
            yield Label("A CSV, Parquet or JSON file, or a folder of them (its subfolders too). ~ is your home folder.", id="note")
            yield Input(value=self.default, placeholder="~/exports   or   ~/Downloads/sales.csv", id="answer", suggester=PathSuggester())
            yield Label("", id="problem")
            yield Label("Tab completes   Enter loads   Esc goes back", id="hint")

    def on_mount(self) -> None:
        """Focus the field, the cursor at the end."""
        field = self.query_one(Input)
        field.focus()
        field.cursor_position = len(field.value)

    def action_complete(self) -> None:
        """Tab: the completion the ghost text shows."""
        field = self.query_one(Input)
        found = complete_path(field.value)
        if found:
            field.value = found
            field.cursor_position = len(found)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter: the path when it exists; otherwise the box stays and says why."""
        value = event.value.strip()
        problem = self.query_one("#problem", Label)
        if not value:
            problem.update("Type a file or folder path first.")
            return
        if not Path(value).expanduser().exists():
            problem.update(f"No such file or folder: {value}")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        """Esc: back, nothing loaded."""
        self.dismiss(None)

