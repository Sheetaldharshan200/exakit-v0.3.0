"""The dashboard's views: status, the catalog, the marketplace with its add-ons and updates tabs, coming soon, the commands, a running job."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, ListItem, ListView, Static, TabbedContent, TabPane

from .panels import LogPane

ACCENT = "green"
SECTIONS = (("status", "Status"), ("catalog", "Catalog"), ("marketplace", "Marketplace"), ("virtual-schemas", "Virtual schemas"),
            ("commands", "Commands"))


class RunJob(Message):
    """A view asks the app to run an action: install an add-on, update everything, start, stop."""

    def __init__(self, kind: str, target: str = "") -> None:
        super().__init__()
        self.kind = kind
        self.target = target


def _kv(text: Text, key: str, value: Any) -> None:
    text.append(f"{key:<18}", style="dim").append(f"{value}\n")


class Card(Vertical):
    """One installed piece: its title, its facts, the actions that fit it."""

    def __init__(self, title: str, lines: Text, actions: list[tuple[str, str, str]], *, state: str = "") -> None:
        super().__init__(classes="card")
        self.title_text, self.lines, self.actions, self.state_word = title, lines, actions, state

    def compose(self) -> ComposeResult:
        """The title with its state, the facts, the buttons."""
        head = Text.assemble((self.title_text, "bold"))
        if self.state_word:
            head.append(f"  {self.state_word}", style=ACCENT if self.state_word == "running" else "dim")
        yield Static(head, classes="card-title")
        yield Static(self.lines, classes="card-text")
        if self.actions:
            with Horizontal(classes="card-actions"):
                for label, kind, target in self.actions:
                    yield Button(label, name=f"{kind}|{target}", variant="success" if kind.endswith("start") else "default", compact=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """An action on this card."""
        kind, target = str(event.button.name).split("|", 1)
        self.post_message(RunJob(kind, target))


def _service_card(name: str, state: str, url: str | None, title: str) -> Card:
    lines = Text()
    if url:
        _kv(lines, "URL", url)
    running = state.startswith("running")
    actions = [("Stop", "service-stop", name)] if running else [("Start", "service-start", name)]
    return Card(title, lines, actions, state=state)


def _component_card(row: dict[str, Any], title: str) -> Card:
    lines = Text()
    _kv(lines, "Installed", row.get("installed_label") or row.get("installed") or "-")
    _kv(lines, "Advertised", row.get("advertised") or "-")
    if row.get("note"):
        _kv(lines, "Note", row["note"])
    actions = [("Update", "update", row["component"])] if row.get("status") == "update_available" else []
    if row["component"] == "mcp":
        actions.append(("Doctor", "mcp-doctor", ""))
    return Card(title, lines, actions, state=str(row.get("status", "")))


class StatusView(VerticalScroll):
    """What ``exakit status`` and ``exakit version`` know, one card per installed piece, each with the actions that fit it."""

    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__(id="view")
        self.state = state

    def compose(self) -> ComposeResult:
        """The cards, or the one line that says the kit is not installed or still loading."""
        doc = self.state.get("status") or {}
        if not doc:
            yield Static(Text("Loading…", style="dim"), id="status-text")
            return
        if not doc.get("installed", True):
            text = Text(f"{doc.get('status')}\n", style="bold")
            if doc.get("remedy"):
                _kv(text, "Next", doc["remedy"])
            yield Static(text, id="status-text")
            return
        with Horizontal(id="actions"):
            yield Button("Start everything", name="start|", variant="success", compact=True)
            yield Button("Stop everything", name="stop|", compact=True)
        with Vertical(id="cards"):
            yield from self.cards(doc)

    def cards(self, doc: dict[str, Any]) -> list[Card]:
        """The database, each service, each other installed component, the datasets, autostart."""
        titles = {e["id"]: e["title"] for e in self.state.get("catalog") or []}
        services = doc.get("services") or {}
        urls = doc.get("urls") or {}
        db_state = "running" if doc.get("running") else str(doc.get("status") or "stopped")
        db = Text()
        _kv(db, "Runtime", (doc.get("runtime") or {}).get("type", "?"))
        _kv(db, "Datasets", ", ".join(doc.get("datasets_loaded") or []) or "none")
        out = [Card(titles.get("personal", "Exasol Personal (the database)"), db,
                    [("Stop", "service-stop", "database")] if doc.get("running") else [("Start", "service-start", "database")], state=db_state)]
        out += [_service_card(name, str(state), urls.get(name), titles.get(name, name)) for name, state in services.items()]
        for row in self.state.get("versions") or []:
            cid = row["component"]
            if row.get("installed") and cid not in services and cid not in ("personal", "exakit"):
                out.append(_component_card(row, titles.get(cid, cid)))
        data = Text()
        _kv(data, "Loaded", ", ".join(doc.get("datasets_loaded") or []) or "none")
        out.append(Card("Sample data", data, [("Load more", "data-load", "")]))
        auto = Text()
        _kv(auto, "At login", "on" if doc.get("autostart") else "off")
        out.append(Card("Autostart", auto, [("Change", "autostart", "")], state="on" if doc.get("autostart") else "off"))
        return out

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Start or stop everything (the cards answer their own buttons)."""
        if event.button.name in ("start|", "stop|"):
            self.post_message(RunJob(str(event.button.name).rstrip("|")))
            event.stop()


class EntryList(Horizontal):
    """A list on the left, the selected entry's detail on the right; shared by the catalog, the marketplace and the commands."""

    def __init__(self, entries: list[dict[str, Any]], *, label: Callable[[dict[str, Any]], str], detail: Callable[[dict[str, Any]], Text],
                 key: str, action: tuple[str, str, Callable[[dict[str, Any]], bool]] | None = None, view_id: str = "view") -> None:
        super().__init__(id=view_id)
        self.entries = entries
        self.label, self.detail_of, self.key, self.action = label, detail, key, action

    def compose(self) -> ComposeResult:
        """The list and the detail."""
        yield ListView(*[ListItem(Label(self.label(e)), name=str(e[self.key])) for e in self.entries], classes="entries")
        with VerticalScroll(classes="detail"):
            yield Static(self.detail_of(self.entries[0]) if self.entries else Text("Nothing here yet.", style="dim"), classes="detail-text")
            if self.action:
                yield Button(self.action[1], id=f"act-{self.action[0]}", disabled=not (self.entries and self.action[2](self.entries[0])))

    def current(self) -> dict[str, Any] | None:
        """The highlighted entry."""
        index = self.query_one(ListView).index
        return self.entries[index] if index is not None and 0 <= index < len(self.entries) else None

    def select(self, ident: str) -> None:
        """Highlight the entry with that id."""
        for index, entry in enumerate(self.entries):
            if str(entry[self.key]) == ident:
                self.query_one(ListView).index = index
                self.query_one(ListView).focus()
                return

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Show the highlighted entry."""
        entry = self.current()
        detail = self.query(".detail-text")
        if entry is not None and detail:
            detail.first(Static).update(self.detail_of(entry))
            if self.action and self.query(Button):
                self.query_one(Button).disabled = not self.action[2](entry)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """The action on the highlighted entry."""
        entry = self.current()
        if entry is not None and self.action:
            self.post_message(RunJob(self.action[0], str(entry[self.key])))


def catalog_detail(entry: dict[str, Any]) -> Text:
    """A component's or add-on's facts."""
    text = Text()
    text.append(f"{entry['title']}\n", style="bold")
    if entry.get("tagline"):
        text.append(f"{entry['tagline']}\n\n", style="dim")
    _kv(text, "Id", entry["id"])
    _kv(text, "Kind", f"{entry['kind']}{' (add-on)' if entry.get('addon') else ''}")
    _kv(text, "Installed", entry.get("installed"))
    _kv(text, "Advertised", entry.get("advertised") or "-")
    _kv(text, "Status", entry.get("status"))
    if entry.get("note"):
        _kv(text, "Note", entry["note"])
    if entry.get("remedy"):
        _kv(text, "Next", entry["remedy"])
    if entry.get("platforms"):
        _kv(text, "Platforms", ", ".join(entry["platforms"]))
    if entry.get("requires"):
        _kv(text, "Requires", ", ".join(entry["requires"]))
    if entry.get("launcher"):
        _kv(text, "Command", entry["launcher"])
    if entry.get("role"):
        text.append(f"\n{entry['role']}\n")
    text.append(f"\nMore: exakit help {entry['id']}", style="dim")
    return text


def marketplace_detail(row: dict[str, Any]) -> Text:
    """An add-on's marketplace row."""
    text = Text()
    text.append(f"{row.get('title') or row['id']}\n", style="bold")
    _kv(text, "Status", row.get("status"))
    _kv(text, "Version", row.get("version") or "-")
    if row.get("reason"):
        text.append(f"\n{row['reason']}\n")
    text.append(f"\nInstall from a shell: exakit marketplace {row['id']}", style="dim")
    return text


def updates_detail(row: dict[str, Any]) -> Text:
    """A component's version row."""
    text = Text()
    text.append(f"{row['component']}\n", style="bold")
    _kv(text, "Installed", row.get("installed_label") or row.get("installed") or "not installed")
    _kv(text, "Advertised", row.get("advertised") or "-")
    _kv(text, "Status", row.get("status"))
    if row.get("note"):
        _kv(text, "Note", row["note"])
    if row.get("remedy"):
        _kv(text, "Next", row["remedy"])
    return text


class MarketplaceView(Vertical):
    """Two tabs: the add-ons (install one) and the updates (update everything)."""

    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__(id="view")
        self.state = state

    def compose(self) -> ComposeResult:
        """The tab strip and the two panes."""
        rows = self.state.get("marketplace") or []
        versions = self.state.get("versions") or []
        with TabbedContent(id="market-tabs"):
            with TabPane("Add-ons", id="addons"):
                yield EntryList(rows, label=lambda r: f"{r['id']:<18} {r.get('status', '')}", detail=marketplace_detail, key="id",
                                action=("marketplace", "Install", lambda r: r.get("status") == "available"), view_id="addons-list")
            with TabPane("Updates", id="updates"):
                yield EntryList(versions, label=lambda r: f"{r['component']:<18} {r.get('status', '')}", detail=updates_detail, key="component",
                                action=("update", "Update everything", lambda _r: True), view_id="updates-list")


class ComingSoonView(Static):
    """Virtual schemas: coming soon."""

    def __init__(self) -> None:
        text = Text()
        text.append("Virtual schemas\n", style="bold")
        text.append("Coming soon. ", style=ACCENT)
        text.append("Browse and query other databases and object stores from Exasol as if they were local schemas.")
        super().__init__(text, id="view")


class JobView(Vertical):
    """A running action: its title and the log with the live rows."""

    def __init__(self, title: str) -> None:
        super().__init__(id="view")
        self.title_text = title

    def compose(self) -> ComposeResult:
        """The title and the log pane."""
        yield Static(Text(self.title_text, style="bold"), id="job-title")
        yield LogPane()
