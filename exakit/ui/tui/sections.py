"""The dashboard's views: status, the catalog, the marketplace with its add-ons and updates tabs, coming soon, the commands, a running job."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static, TabbedContent, TabPane

from exakit.domain import ownership
from exakit.ui.widgets import Option

from .choices import ChoiceList
from .facts import Facts
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


class Card(Vertical):
    """One installed piece: its title, its facts, the actions that fit it."""

    def __init__(self, title: str, lines: Facts, actions: list[tuple[str, str, str]], *, state: str = "") -> None:
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
                    yield Button(label, name=f"{kind}|{target}", variant=_variant(kind), compact=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """An action on this card."""
        kind, target = str(event.button.name).split("|", 1)
        self.post_message(RunJob(kind, target))


def _variant(kind: str) -> str:
    """Start is green, stop is red, everything else plain."""
    if kind.endswith("stop"):
        return "error"
    return "success" if kind.endswith("start") else "default"


def _service_card(name: str, state: str, url: str | None, title: str, row: dict[str, Any], extra: dict[str, Any] | None = None) -> Card:
    lines = Facts()
    if url:
        lines.kv("URL", url)
    lines.kv("Version", f"{row.get('installed_label') or '-'}  (advertised {row.get('advertised') or '-'})")
    if extra:
        lines.kv("Tasks", f"{extra.get('tasks', '-')} ({extra.get('enabled', '-')} enabled)  in {extra.get('schema', 'SCHED')}.SCHED_TASKS")
        lines.kv("Last run", f"{extra.get('last_run') or '-'}  {extra.get('last_status') or ''}".rstrip())
        lines.kv("Failures (24h)", extra.get("failures_24h", "-"))
    running = state.startswith("running")
    actions = [("Stop", "service-stop", name)] if running else [("Start", "service-start", name)]
    if not running and name == "exasol-scheduler":
        actions.append(("Repair", "update", name))        # exakit update exasol-scheduler re-runs the user setup and the engine
    return Card(title, lines, actions, state=state)


def _component_card(row: dict[str, Any], title: str, record: dict[str, Any]) -> Card:
    lines = Facts()
    lines.kv("Installed", row.get("installed_label") or row.get("installed") or "-")
    lines.kv("Advertised", row.get("advertised") or "-")
    if row["component"] == "mcp":
        connection = ((record.get("components") or {}).get("mcp_server") or {}).get("connection") or {}
        lines.kv("DB user", connection.get("user") or "mcp_readonly")
        if connection.get("password_file"):
            lines.kv("Password", _tilde(connection["password_file"]))
    if row.get("note"):
        lines.kv("Note", row["note"])
    actions = [("Update", "update", row["component"])] if row.get("status") == "update_available" else []
    if row["component"] == "mcp":
        actions.append(("Doctor", "mcp-doctor", ""))
    return Card(title, lines, actions, state=str(row.get("status", "")))


def _tilde(path: Any) -> str:
    text = str(path or "")
    home = str(Path.home())
    return text.replace(home, "~", 1) if home and text.startswith(home) else text


class StatusView(VerticalScroll):
    """What the kit knows about itself, one card per installed piece, each with the actions that fit it."""

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
            text = Facts().line(f"{doc.get('status')}\n", "bold")
            if doc.get("remedy"):
                text.kv("Next", doc["remedy"])
            yield Static(text, id="status-text")
            return
        all_running = bool(doc.get("running")) and all(str(s).startswith("running") for s in (doc.get("services") or {}).values())
        with Horizontal(id="actions"):
            yield Button("Start everything", name="start|", variant="default" if all_running else "success", compact=True)
            yield Button("Stop everything", name="stop|", variant="error", compact=True)
        with Vertical(id="cards"):
            yield from self.cards(doc)

    def cards(self, doc: dict[str, Any]) -> list[Card]:
        """The kit, the database, each service, each other installed component, the datasets, autostart."""
        titles = {e["id"]: e["title"] for e in self.state.get("catalog") or []}
        rows = {r["component"]: r for r in self.state.get("versions") or []}
        record = self.state.get("info") or {}
        services = doc.get("services") or {}
        out = [self._kit_card(rows.get("exakit") or {}, record, doc), self._database_card(doc, record, rows.get("personal") or {}, titles)]
        for name, state in services.items():
            extra = self.state.get("scheduler") if name == "exasol-scheduler" else None
            out.append(_service_card(name, str(state), (doc.get("urls") or {}).get(name), titles.get(name, name), rows.get(name) or {}, extra or None))
        for cid, row in rows.items():
            if row.get("installed") and cid not in services and cid not in ("personal", "exakit"):
                out.append(_component_card(row, titles.get(cid, cid), record))
        data = Facts()
        data.kv("Loaded", ", ".join(doc.get("datasets_loaded") or []) or "none")
        data.kv("Source", doc.get("datasets_source") or "-")
        out.append(Card("Sample data", data, [("Load more", "data-load", "")]))
        auto = Facts()
        auto.kv("At login", "on" if doc.get("autostart") else "off")
        out.append(Card("Autostart", auto, [("Change", "autostart", "")], state="on" if doc.get("autostart") else "off"))
        return out

    def _kit_card(self, row: dict[str, Any], record: dict[str, Any], doc: dict[str, Any]) -> Card:
        text = Facts()
        text.kv("Version", row.get("installed_label") or (record.get("kit") or {}).get("version") or "-")
        text.kv("Advertised", row.get("advertised") or "-")
        text.kv("Source", (record.get("kit") or {}).get("source") or "-")
        text.kv("Record", _tilde(doc.get("manifest")))
        if doc.get("persona"):
            text.kv("Persona", doc["persona"])
        actions = [("Update", "update", "")] if row.get("status") == "update_available" else []
        return Card("Starter kit", text, actions, state=str(row.get("status") or ""))

    def _database_card(self, doc: dict[str, Any], record: dict[str, Any], row: dict[str, Any], titles: dict[str, str]) -> Card:
        runtime = record.get("runtime") or {}
        text = Facts()
        text.kv("DSN", runtime.get("dsn") or "unknown")
        text.kv("Admin user", runtime.get("user") or "sys")
        if runtime.get("password_file"):
            text.kv("Password", _tilde(runtime["password_file"]))
        owners = record.get("ownership") or {}
        yours = "  - yours, adopted" if owners.get("launcher") == ownership.ADOPTED else ""
        text.kv("Launcher", f"{row.get('installed_label') or '-'}  (advertised {row.get('advertised') or '-'}){yours}")
        text.kv("TLS", "self-signed certificate")
        if owners.get("database", ownership.KIT) != ownership.KIT:
            text.kv("Managed by", ownership.word(owners.get("database")))
        state = "running" if doc.get("running") else str(doc.get("status") or "stopped")
        actions = [("Stop", "service-stop", "database")] if doc.get("running") else [("Start", "service-start", "database")]
        return Card(titles.get("personal", "Exasol Personal (the database)"), text, actions, state=state)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Start or stop everything (the cards answer their own buttons)."""
        if event.button.name in ("start|", "stop|"):
            self.post_message(RunJob(str(event.button.name).rstrip("|")))
            event.stop()


class EntryList(Horizontal):
    """A list on the left, the selected entry's detail on the right; shared by the catalog, the marketplace and the commands."""

    def __init__(self, entries: list[dict[str, Any]], *, label: Callable[[dict[str, Any]], str], detail: Callable[[dict[str, Any]], Facts],
                 key: str, action: tuple[str, str, Callable[[dict[str, Any]], bool]] | None = None, view_id: str = "view") -> None:
        super().__init__(id=view_id)
        self.entries = entries
        self.label, self.detail_of, self.key, self.action = label, detail, key, action

    def compose(self) -> ComposeResult:
        """The list and the detail."""
        yield ChoiceList([Option(str(e[self.key]), *self._columns(e)) for e in self.entries], single=True, widget_id="entries", classes="entries", marks=False)
        with VerticalScroll(classes="detail"):
            yield Static(self.detail_of(self.entries[0]) if self.entries else Text("Nothing here yet.", style="dim"), classes="detail-text")
            if self.action:
                yield Button(self.action[1], id=f"act-{self.action[0]}", disabled=not (self.entries and self.action[2](self.entries[0])))

    def _columns(self, entry: dict[str, Any]) -> tuple[str, str]:
        """The row as (name column, status column): the label function's two halves, padded by the list."""
        text = self.label(entry)
        head, _, rest = text.partition("  ")
        return head.strip(), rest.strip()

    def current(self) -> dict[str, Any] | None:
        """The entry under the cursor."""
        index = self.query_one(ChoiceList).cursor
        return self.entries[index] if 0 <= index < len(self.entries) else None

    def select(self, ident: str) -> None:
        """Put the cursor on the entry with that id."""
        for index, entry in enumerate(self.entries):
            if str(entry[self.key]) == ident:
                self.query_one(ChoiceList).go_to(index)
                self.query_one(ChoiceList).focus()
                self._show(entry)
                return

    def on_choice_list_moved(self, event: ChoiceList.Moved) -> None:
        """Show the entry under the cursor."""
        self._show(self.current())

    def on_choice_list_chosen(self, event: ChoiceList.Chosen) -> None:
        """Enter or a click: the entry's action, when it has one that applies."""
        entry = self.current()
        if entry is not None and self.action and self.action[2](entry):
            self.post_message(RunJob(self.action[0], str(entry[self.key])))

    def _show(self, entry: dict[str, Any] | None) -> None:
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


def _presence(entry: dict[str, Any]) -> tuple[str, str]:
    """(installed, status) in words: an add-on the kit did not install is said so, not called unknown."""
    market = str(entry.get("market") or "")
    if market in ("system", "managed outside the kit", "already on this system"):
        return "yes - installed outside the kit, not managed by exakit", "present (managed outside the kit)"
    if market in ("unavailable", "not available on this machine"):
        reason = entry.get("market_reason") or ""
        return "no - not available on this machine", f"unavailable{': ' + reason if reason else ''}"
    if market in ("available",):
        return f"no (install with: exakit marketplace {entry['id']})", "available in the marketplace"
    status = str(entry.get("status") or "")
    return str(entry.get("installed") or "not installed"), status if status != "unknown" else ("installed" if market == "installed" else "not installed")


def catalog_detail(entry: dict[str, Any], help_text: str = "") -> Facts:
    """A component's or add-on's facts, then its full help page (what ``exakit help <id>`` prints)."""
    text = Facts()
    text.line(f"{entry['title']}\n", "bold")
    if entry.get("tagline"):
        text.line(f"{entry['tagline']}\n\n", "dim")
    text.kv("Id", entry["id"])
    text.kv("Kind", f"{entry['kind']}{' (add-on)' if entry.get('addon') else ''}")
    installed, status = _presence(entry)
    text.kv("Installed", installed)
    text.kv("Advertised", entry.get("advertised") or "-")
    text.kv("Status", status)
    if entry.get("note"):
        text.kv("Note", entry["note"])
    if entry.get("remedy"):
        text.kv("Next", entry["remedy"])
    if entry.get("platforms"):
        text.kv("Platforms", ", ".join(entry["platforms"]))
    if entry.get("requires"):
        text.kv("Requires", ", ".join(entry["requires"]))
    if entry.get("launcher"):
        text.kv("Command", entry["launcher"])
    if entry.get("managed"):
        text.kv("Managed", entry["managed"])
    if entry.get("role"):
        text.line(f"\n{entry['role']}\n")
    if help_text.strip():
        text.line("\n" + _without_header(help_text).rstrip() + "\n")
    else:
        text.line(f"\nMore: exakit help {entry['id']}", "dim")
    return text


def _without_header(page: str) -> str:
    """A help page minus its boxed title (two rules around the name): the facts above already say it."""
    lines = page.splitlines()
    rules = [i for i, line in enumerate(lines[:6]) if line.strip() and set(line.strip()) <= {"-", "─"}]
    return "\n".join(lines[rules[1] + 1:]).lstrip("\n") if len(rules) >= 2 else page


def marketplace_detail(row: dict[str, Any]) -> Facts:
    """An add-on's marketplace row."""
    text = Facts()
    text.line(f"{row.get('title') or row['id']}\n", "bold")
    text.kv("Status", row.get("status"))
    text.kv("Version", row.get("version") or "-")
    if row.get("reason"):
        text.line(f"\n{row['reason']}\n")
    text.line(f"\nInstall from a shell: exakit marketplace {row['id']}", "dim")
    return text


def updates_detail(row: dict[str, Any]) -> Facts:
    """A component's version row."""
    text = Facts()
    text.line(f"{row['component']}\n", "bold")
    text.kv("Installed", row.get("installed_label") or row.get("installed") or "not installed")
    text.kv("Advertised", row.get("advertised") or "-")
    text.kv("Status", row.get("status"))
    if row.get("note"):
        text.kv("Note", row["note"])
    if row.get("remedy"):
        text.kv("Next", row["remedy"])
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
                pending = sum(1 for r in versions if r.get("status") == "update_available")
                with Horizontal(id="updates-header"):
                    yield Static(Text(f"{pending} update{'s' if pending != 1 else ''} pending" if pending else "Everything is current", style="dim"), id="updates-note")
                    yield Button("Update everything", name="update|", disabled=not pending, compact=True)
                yield EntryList(versions, label=lambda r: f"{r['component']:<18} {r.get('status', '')}", detail=updates_detail, key="component",
                                action=("update", "Update this one", lambda r: r.get("status") == "update_available"), view_id="updates-list")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Update everything, from the header (the rows answer their own button)."""
        if event.button.name == "update|":
            self.post_message(RunJob("update", ""))
            event.stop()


class ComingSoonView(Static):
    """Virtual schemas: coming soon."""

    def __init__(self) -> None:
        text = Facts()
        text.line("Virtual schemas\n", "bold")
        text.line("Coming soon. ", ACCENT)
        text.line("Browse and query other databases and object stores from Exasol as if they were local schemas.")
        self.facts = text
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
