"""The dashboard (design 6.1a): a sidebar, the views, a search bar that completes as you type, actions run as the ordinary commands."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Footer, Input, Label, ListItem, ListView, OptionList
from textual.widgets.option_list import Option as ListOption

from exakit.domain.errors import ExakitError
from exakit.domain.plan import Plan, Step
from exakit.ui.progress import ProgressState

from .palette import KitProvider
from .panels import LogPane, ProgressRow, WordmarkHeader
from .sections import SECTIONS, ComingSoonView, EntryList, JobView, MarketplaceView, RunJob, StatusView, catalog_detail

LOADING = ("status", "versions", "catalog", "marketplace", "commands")


class SearchBar(Vertical):
    """An input that completes inline (Tab accepts) and lists the matches as you type; Enter opens the best one."""

    def __init__(self) -> None:
        super().__init__(id="search")
        self.entries: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        """The input and the results list."""
        yield Input(placeholder="Search commands and components   (Tab completes, Enter opens, / focuses)", id="search-input")
        yield OptionList(id="results", classes="hidden")

    def set_entries(self, entries: list[tuple[str, str, str]]) -> None:
        """The searchable entries; the inline completion knows their ids and labels."""
        self.entries = [e for e in entries if e[0] != "section"]
        words = sorted({e[1] for e in self.entries} | {e[2] for e in self.entries})
        self.query_one(Input).suggester = SuggestFromList(words, case_sensitive=False)

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
        results = self.query_one(OptionList)
        found = self.matches(event.value)
        results.clear_options()
        results.add_options([ListOption(Text.assemble((e[1], "bold"), f"  {e[2]}"), id=f"{e[0]}:{e[1]}") for e in found])
        results.set_class(not found, "hidden")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter opens the best match."""
        found = self.matches(event.value)
        if found:
            self.app.call_later(self.app.open_entry, found[0][0], found[0][1])     # type: ignore[attr-defined]
            self.query_one(Input).value = ""

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """A chosen result opens."""
        kind, ident = str(event.option.id).split(":", 1)
        self.app.call_later(self.app.open_entry, kind, ident)     # type: ignore[attr-defined]
        self.query_one(Input).value = ""

    def on_key(self, event) -> None:
        """Down from the input moves into the results."""
        if event.key == "down" and self.query_one(Input).has_focus and not self.query_one(OptionList).has_class("hidden"):
            self.query_one(OptionList).focus()
            event.stop()


class DashboardApp(App[None]):
    """The sidebar on the left, the view on the right, the search on top, the palette on Ctrl-P."""

    CSS_PATH = "app.tcss"
    COMMANDS = App.COMMANDS | {KitProvider}
    BINDINGS = [Binding("ctrl+q", "quit", "Quit"), Binding("slash", "focus_search", "Search"), Binding("r", "reload", "Refresh"),
                Binding("escape", "to_sidebar", "Sidebar", show=False), Binding("ctrl+c", "copy_or_hint", "Copy", show=False, priority=True)]

    def __init__(self, data, *, title: str) -> None:
        super().__init__(ansi_color=True)
        self.data = data
        self.title_text = title
        self.state: dict[str, Any] = {}
        self.section = "status"
        self.job_running = False
        self.pending_open: tuple[str, str] | None = None

    # --- layout ------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Header, search, sidebar beside the view, footer."""
        yield WordmarkHeader(self.title_text, "the dashboard")
        yield SearchBar()
        with Horizontal(id="body"):
            yield ListView(*[ListItem(Label(label), name=key) for key, label in SECTIONS], id="sidebar")
            yield Vertical(id="content")
        yield Footer()

    async def on_mount(self) -> None:
        """Load the data in a worker and show the status."""
        self.query_one("#sidebar", ListView).focus()
        await self.show_section("status")
        self.run_worker(self._load, thread=True, exit_on_error=False, name="load")

    def _load(self) -> None:
        payload = {name: getattr(self.data, name)() for name in LOADING}
        self.call_from_thread(self._loaded, payload)

    async def _loaded(self, payload: dict[str, Any]) -> None:
        self.state.update(payload)
        self.query_one(SearchBar).set_entries(self.entries())
        if not self.job_running and not self.query(JobView):      # a finished job's log stays until Esc
            await self.show_section(self.section)
        if self.pending_open:
            kind, ident = self.pending_open
            self.pending_open = None
            await self.open_entry(kind, ident)

    def entries(self) -> list[tuple[str, str, str]]:
        """Everything the search and the palette can open: sections, commands, components and add-ons."""
        found = [("section", key, label) for key, label in SECTIONS]
        found += [("command", c["command"].split()[0], c["summary"]) for c in self.state.get("commands") or []]
        found += [("item", e["id"], e["title"]) for e in self.state.get("catalog") or []]
        return found

    # --- the views -----------------------------------------------------------------------------

    def _view(self, name: str):
        if name == "status":
            return StatusView(self.state)
        if name == "catalog":
            return EntryList(self.state.get("catalog") or [], label=lambda e: f"{e['id']:<18} {e.get('status', '')}", detail=catalog_detail, key="id")
        if name == "marketplace":
            return MarketplaceView(self.state)
        if name == "commands":
            return EntryList(self.state.get("commands") or [], label=lambda c: f"{c['command']:<18} {c.get('group', '')}",
                             detail=lambda c: Text(self.data.help_page(c["command"].split()[0]) or c.get("summary", "")), key="command")
        return ComingSoonView()

    async def show_section(self, name: str) -> None:
        """Replace the view with the section's."""
        self.section = name
        content = self.query_one("#content", Vertical)
        await content.remove_children()
        await content.mount(self._view(name))
        sidebar = self.query_one("#sidebar", ListView)
        index = [key for key, _ in SECTIONS].index(name)
        if sidebar.index != index:
            sidebar.index = index

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Arrows on the sidebar switch the view."""
        if event.list_view.id == "sidebar" and event.item is not None and event.item.name and event.item.name != self.section and not self.job_running:
            await self.show_section(event.item.name)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter or a click on the sidebar switches the view and moves into it."""
        if event.list_view.id == "sidebar" and event.item is not None and event.item.name:
            if self.job_running:
                self.notify("An action is running - the view comes back when it finishes", timeout=3)
                return
            await self.show_section(event.item.name)
            lists = self.query("#view ListView")
            if lists:
                lists.first().focus()

    async def open_entry(self, kind: str, ident: str) -> None:
        """Open a section, a command's page or a component's detail (the search, the palette)."""
        if kind == "section":
            await self.show_section(ident)
            return
        if not self.state:
            self.pending_open = (kind, ident)
            return
        await self.show_section("commands" if kind == "command" else "catalog")
        self.query_one("#view", EntryList).select(ident)

    # --- actions ------------------------------------------------------------------------------------

    async def on_run_job(self, message: RunJob) -> None:
        """A view asked for an action: run the ordinary command in a worker with the screens as its renderer."""
        if self.job_running:
            self.notify("One action at a time - this one is still running", timeout=3)
            return
        self.job_running = True
        content = self.query_one("#content", Vertical)
        await content.remove_children()
        await content.mount(JobView(f"exakit {message.kind}{' ' + message.target if message.target else ''}"))
        job = self.data.job(message.kind, message.target)
        self.run_worker(lambda: self._job(job), thread=True, exit_on_error=False, name="job")

    def _job(self, job) -> None:
        try:
            result = job()
            summary = f"Done: {result.status}" + (f"  Next: {result.remedy}" if result.remedy else "")
        except ExakitError as err:
            summary = f"Stopped: {err.message}" + (f"  Fix: {err.remedy}" if err.remedy else "")
        except Exception as err:      # the dashboard stays up; the log has the details
            summary = f"Stopped: {type(err).__name__}: {err}"
        self.call_from_thread(self._job_done, summary)

    async def _job_done(self, summary: str) -> None:
        await self.write(Text(""))
        await self.write(Text(summary, style="bold"))
        await self.write(Text("Press Esc for the sidebar; the views refresh now.", style="dim"))
        self.job_running = False
        self.run_worker(self._load, thread=True, exit_on_error=False, name="load")

    # --- what TuiRenderer asks for during an action ----------------------------------------------------

    async def _log(self) -> LogPane:
        panes = self.query(LogPane)
        if panes:
            return panes.first()
        content = self.query_one("#content", Vertical)
        await content.remove_children()
        view = JobView("exakit")
        await content.mount(view)
        return view.query_one(LogPane)

    async def write(self, text: Text) -> None:
        """A line into the job log."""
        (await self._log()).write(text)

    async def set_title(self, title: str, subtitle: str = "") -> None:
        """A command's banner: a bold line in the job log."""
        await self.write(Text(title, style="bold"))

    async def set_plan(self, plan: Plan) -> None:
        """A plan: its steps as lines."""
        for step in plan.steps:
            await self.write(Text(f"  {step.state.value:<8} {step.label or step.id}"))

    async def step_begin(self, step: Step | str) -> None:
        """A step starts."""
        await self.write(Text(step if isinstance(step, str) else (step.label or step.id), style="bold"))

    async def step_end(self, step: Step | str, *, ok: bool, detail: str) -> None:
        """A step ends."""
        label = step if isinstance(step, str) else (step.label or step.id)
        await self.write(Text.assemble(("✓ " if ok else "✗ ", "green" if ok else "red"), label, (f"  {detail}" if detail else "", "dim")))

    async def live_begin(self, state: ProgressState) -> ProgressRow:
        """A job's live row."""
        return (await self._log()).live_begin(state)

    async def live_end(self, row: ProgressRow) -> None:
        """The live row goes."""
        await (await self._log()).live_end(row)

    async def ask(self, screen: ModalScreen) -> Any:
        """A modal question from the running command."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.push_screen(screen, callback=future.set_result)
        return await future

    # --- keys -----------------------------------------------------------------------------------------

    def action_focus_search(self) -> None:
        """/ focuses the search."""
        self.query_one("#search-input", Input).focus()

    def action_reload(self) -> None:
        """r reloads the data."""
        self.run_worker(self._load, thread=True, exit_on_error=False, name="load")

    async def action_to_sidebar(self) -> None:
        """Esc returns to the sidebar (and the section's view after a job)."""
        if not self.job_running and self.query(JobView):
            await self.show_section(self.section)
        self.query_one("#sidebar", ListView).focus()

    def action_copy_or_hint(self) -> None:
        """Ctrl-C copies the selected text, or says how to select and how to quit."""
        selected = self.screen.get_selected_text()
        if selected:
            self.copy_to_clipboard(selected)
            self.notify("Copied", timeout=2)
            return
        self.notify("Ctrl-Q quits. Drag to select text (hold Option on a Mac terminal), then Ctrl-C copies.", timeout=4)
