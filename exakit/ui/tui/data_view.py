"""The Data load view: the bundled datasets and your own files on the left, what each is and a Load button on the right."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static

from exakit.ui.widgets import Option

from .choices import ChoiceList
from .facts import Facts
from .screens import PathScreen
from .layout import fitted_width, place_list
from .sections import RunJob

LOCAL = "local"
CHOOSE = "Choose a file or folder…"


def _tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path and path.startswith(home) else path


class DataLoadView(Horizontal):
    """One row per bundled dataset plus "your own file or folder"; Enter or the mouse shows the detail; Load runs ``exakit data-load``."""

    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__(id="view")
        doc = state.get("datasets") or {}
        self.items: list[dict[str, Any]] = list(doc.get("items") or [])
        self.last_load: dict[str, Any] = dict(doc.get("last_load") or {})

    def compose(self) -> ComposeResult:
        """The list and the detail."""
        rows = [Option(LOCAL, "Your own file or folder", ""), Option("_gap", "", heading=True), Option("_sample", "Sample data", heading=True)]
        rows += [Option(d["id"], d["label"], "loaded" if d.get("loaded") else "not loaded") for d in self.items]
        self.fitted = fitted_width(rows, most=60)               # dataset labels are long; place_list caps the share
        choices = ChoiceList(rows, single=True, widget_id="entries", classes="entries", marks=False)
        choices.styles.width = self.fitted
        yield choices
        with VerticalScroll(classes="detail"):
            yield Static(self._detail(self.current()), classes="detail-text", id="data-detail")
            with Vertical(id="data-actions"):
                yield Button(CHOOSE, id="data-load-button", variant="success", compact=True)

    def on_resize(self) -> None:
        """Beside the detail, or above it in a narrow terminal."""
        lists = self.query(ChoiceList)
        if lists:
            place_list(self, lists.first(), self.fitted)

    def on_mount(self) -> None:
        """The button and the path box for the first row, once the widgets exist."""
        self._refresh()

    def current(self) -> dict[str, Any] | None:
        """The dataset under the cursor; None for "your own file or folder" (the first row)."""
        lists = self.query(ChoiceList)
        if not lists or not lists.first().options:
            return None
        rows = lists.first()
        ident = rows.options[rows.cursor].id
        return next((d for d in self.items if d["id"] == ident), None)

    def select(self, ident: str) -> None:
        """Put the cursor on a row (the search, the palette)."""
        rows = self.query_one(ChoiceList)
        for index, option in enumerate(rows.options):
            if option.id == ident:
                rows.go_to(index)
                rows.focus()
                self._refresh()
                return

    def _detail(self, item: dict[str, Any] | None) -> Facts:
        text = Facts()
        if item is None:
            text.line("Your own file or folder\n", "bold")
            text.line("A CSV, Parquet or JSON file lands in a table named after it; a folder loads every such file into a schema named after the folder, "
                      "and its subfolders into schemas of their own (a tree to tick).\n\n", "dim")
            if self.last_load:
                text.kv("Last load", f"{self.last_load.get('target') or '-'}  from {_tilde(str(self.last_load.get('source') or '')) or '-'}")
            text.line("\nEnter, a click or the button opens a box for the path; Tab completes it.", "dim")
            return text
        text.line(f"{item['label']}\n", "bold")
        text.kv("Id", item["id"])
        text.kv("Schema", item.get("schema") or "-")
        text.kv("Status", "loaded" if item.get("loaded") else "not loaded")
        if item.get("tables"):
            text.kv("Tables", f"{len(item['tables'])}  ({item.get('rows', 0):,} rows)")
        text.line("\nLoad puts the dataset into its schema; loaded already, it replaces the schema's tables (exakit data-load --force).", "dim")
        return text

    def _refresh(self) -> None:
        """The detail, the path box and the button follow the cursor. A view the dashboard already replaced (its data came
        back and the section was rebuilt) has no widgets left: a late call does nothing."""
        if not self.is_attached or not self.query("#data-detail"):
            return
        item = self.current()
        self.query_one("#data-detail", Static).update(self._detail(item))
        button = self.query_one("#data-load-button", Button)
        button.label = CHOOSE if item is None else ("Load" if not item.get("loaded") else "Reload (replace)")
        button.variant = "success" if item is None or not item.get("loaded") else "default"

    def on_choice_list_moved(self, event: ChoiceList.Moved) -> None:
        """A new row under the cursor."""
        self._refresh()

    def on_choice_list_chosen(self, event: ChoiceList.Chosen) -> None:
        """Enter or a click: your own file or folder opens the path box; a dataset only shows (its button loads it)."""
        self._refresh()
        if self.current() is None:
            self._ask_path()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Load what the cursor is on."""
        self._load()
        event.stop()

    def _load(self) -> None:
        item = self.current()
        if item is None:
            self._ask_path()
            return
        self.post_message(RunJob("data-load", f"{'reload' if item.get('loaded') else 'dataset'}:{item['id']}"))

    def _ask_path(self) -> None:
        """The path box over the page: full width whatever the terminal, prefilled with the last folder or file loaded."""
        last = str(self.last_load.get("source") or "") if str(self.last_load.get("type") or "").startswith("local") else ""
        self.app.push_screen(PathScreen("Load your own file or folder", _tilde(last)), self._path_given)

    def _path_given(self, path: str | None) -> None:
        if path:
            self.post_message(RunJob("data-load", f"path:{path}"))
