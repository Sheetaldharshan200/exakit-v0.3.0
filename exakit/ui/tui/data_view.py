"""The Data load view: the bundled datasets and your own files on the left, what each is and a Load button on the right."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from exakit.ui.widgets import Option

from .choices import ChoiceList
from .facts import Facts
from .sections import RunJob

LOCAL = "local"


class DataLoadView(Horizontal):
    """One row per bundled dataset plus "your own file or folder"; Enter or the mouse shows the detail; Load runs ``exakit data-load``."""

    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__(id="view")
        doc = state.get("datasets") or {}
        self.items: list[dict[str, Any]] = list(doc.get("items") or [])
        self.last_load: dict[str, Any] = dict(doc.get("last_load") or {})

    def compose(self) -> ComposeResult:
        """The list and the detail."""
        rows = [Option(d["id"], d["label"], "loaded" if d.get("loaded") else "not loaded") for d in self.items]
        rows.append(Option(LOCAL, "Your own file or folder", ""))
        yield ChoiceList(rows, single=True, widget_id="entries", classes="entries", marks=False)
        with VerticalScroll(classes="detail"):
            yield Static(self._detail(self.current()), classes="detail-text", id="data-detail")
            yield Input(placeholder="~/exports  or  ./sales.csv", id="data-path")
            with Vertical(id="data-actions"):
                yield Button("Load", id="data-load-button", variant="success", compact=True)
        self.call_after_refresh(self._refresh)

    def current(self) -> dict[str, Any] | None:
        """The dataset under the cursor; None for the local row."""
        lists = self.query(ChoiceList)
        index = lists.first().cursor if lists else 0
        return self.items[index] if 0 <= index < len(self.items) else None

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
                text.kv("Last load", f"{self.last_load.get('target') or '-'}  from {self.last_load.get('source') or '-'}")
            text.line("\nType the path below, then Load.", "dim")
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
        """The detail, the path box and the button follow the cursor."""
        item = self.current()
        self.query_one("#data-detail", Static).update(self._detail(item))
        self.query_one("#data-path", Input).display = item is None
        button = self.query_one("#data-load-button", Button)
        button.label = "Load" if item is None or not item.get("loaded") else "Reload (replace)"
        button.variant = "success" if item is None or not item.get("loaded") else "default"

    def on_choice_list_moved(self, event: ChoiceList.Moved) -> None:
        """A new row under the cursor."""
        self._refresh()

    def on_choice_list_chosen(self, event: ChoiceList.Chosen) -> None:
        """Enter or a click on a row: show it (the button loads)."""
        self._refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the path box loads the path."""
        self._load()
        event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Load what the cursor is on."""
        self._load()
        event.stop()

    def _load(self) -> None:
        item = self.current()
        if item is None:
            path = self.query_one("#data-path", Input).value.strip()
            if not path:
                self.notify("Type a file or folder path first", timeout=3)
                return
            self.post_message(RunJob("data-load", f"path:{path}"))
            return
        self.post_message(RunJob("data-load", f"{'reload' if item.get('loaded') else 'dataset'}:{item['id']}"))
