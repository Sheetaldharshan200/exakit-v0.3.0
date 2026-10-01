"""The dashboard (design 6.1a): a sidebar, the views, a search bar that completes as you type, actions run as the ordinary commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Footer, Input

from exakit.ui.widgets import Option

from exakit.domain.errors import ExakitError
from exakit.domain.plan import Plan, Step
from exakit.ui.progress import ProgressState

from .choices import ChoiceList
from .palette import KitProvider
from .panels import Loader, LogPane, ProgressRow, WordmarkHeader
from .sections import SECTIONS, ComingSoonView, EntryList, JobView, MarketplaceView, RunJob, StatusView, catalog_detail

LOADING = ("status", "versions", "catalog", "marketplace", "commands", "info", "scheduler")
QUIET_LEVELS = {"INFO", "OK"}        # these lines came through the renderer already; the tail shows the rest (CMD, LAUNCHER, DATA, WARN...)


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


class DashboardApp(App[None]):
    """The sidebar on the left, the view on the right, the search on top, the palette on Ctrl-P."""

    CSS_PATH = "app.tcss"
    COMMANDS = App.COMMANDS | {KitProvider}
    BINDINGS = [Binding("ctrl+q", "quit", "Quit"), Binding("slash", "focus_search", "Search"), Binding("r", "reload", "Refresh"),
                Binding("escape", "to_sidebar", "Sidebar", show=False), Binding("ctrl+c", "copy_or_hint", "Copy", show=False, priority=True),
                Binding("super+c", "copy_or_hint", "Copy", show=False, priority=True)]

    def __init__(self, data, *, title: str) -> None:
        super().__init__(ansi_color=True)
        self.data = data
        self.title_text = title
        self.state: dict[str, Any] = {}
        self.section = "status"
        self.job_running = False
        self.pending_open: tuple[str, str] | None = None
        self._running_row = None
        self._tail_at = 0
        self._tail_timer = None

    # --- layout ------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Header, search, sidebar beside the view, footer."""
        yield WordmarkHeader(self.title_text, "the dashboard")
        yield SearchBar()
        with Horizontal(id="body"):
            yield ChoiceList([Option(key, label) for key, label in SECTIONS], single=True, widget_id="sidebar", marks=False)
            yield Vertical(id="content")
        yield Footer()

    async def on_mount(self) -> None:
        """Load the data in a worker and show the status."""
        self.query_one("#sidebar", ChoiceList).focus()
        await self.show_section("status")
        self.run_worker(self._load, thread=True, exit_on_error=False, name="load")

    def _load(self) -> None:
        self.call_from_thread(self._loading, True)
        payload = {name: getattr(self.data, name)() for name in LOADING}
        self.call_from_thread(self._loaded, payload)

    def _loading(self, on: bool) -> None:
        loaders = self.query(Loader)
        if loaders:
            loaders.first().start() if on else loaders.first().stop()

    async def _loaded(self, payload: dict[str, Any]) -> None:
        if not self.is_running or not self.query("#content"):
            return
        self._loading(False)
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
        sidebar = self.query_one("#sidebar", ChoiceList)
        index = [key for key, _ in SECTIONS].index(name)
        if sidebar.cursor != index:
            sidebar.cursor = index
            sidebar.redraw()

    async def on_choice_list_moved(self, event: ChoiceList.Moved) -> None:
        """Arrows on the sidebar switch the view."""
        if getattr(event.control, "id", None) == "sidebar" and not self.job_running:
            name = SECTIONS[event.index][0]
            if name != self.section:
                await self.show_section(name)

    async def on_choice_list_chosen(self, event: ChoiceList.Chosen) -> None:
        """Enter or a click on the sidebar switches the view and moves into it."""
        if getattr(event.control, "id", None) != "sidebar":
            return
        if self.job_running:
            self.notify("An action is running - the view comes back when it finishes", timeout=3)
            return
        await self.show_section(SECTIONS[event.index][0])
        lists = self.query("#view ChoiceList")
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
        self._running_row = await self.live_begin(ProgressState(f"exakit {message.kind} {message.target}".strip(), unit="spinner"))
        self._start_tail()
        self.run_worker(lambda: self._job(job), thread=True, exit_on_error=False, name="job")

    def _start_tail(self) -> None:
        """Follow the kit's log while the action runs: the lines the renderer did not already show."""
        path = self.data.log_path() if hasattr(self.data, "log_path") else None
        self._tail_path = Path(path) if path else None
        self._tail_at = self._tail_path.stat().st_size if self._tail_path and self._tail_path.exists() else 0
        if self._tail_path:
            self._tail_timer = self.set_interval(0.5, self._tail_once)

    async def _tail_once(self) -> None:
        if not self._tail_path or not self._tail_path.exists():
            return
        with self._tail_path.open("rb") as handle:
            handle.seek(self._tail_at)
            chunk = handle.read()
        self._tail_at += len(chunk)
        for raw in chunk.decode("utf-8", errors="replace").splitlines():
            parts = raw.split(" ", 3)        # "YYYY-MM-DD HH:MM:SS LEVEL message"
            if len(parts) == 4 and parts[2].isupper() and parts[2] not in QUIET_LEVELS:
                await self.write(Text.assemble((f"{parts[2]:<9}", "dim"), (parts[3], "dim")))

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
        if self._tail_timer is not None:
            self._tail_timer.stop()
            self._tail_timer = None
            await self._tail_once()
        if self._running_row is not None:
            await self.live_end(self._running_row)
            self._running_row = None
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

    async def set_aside(self, title: str, lines: list[str]) -> None:
        """What the screens show beside the log: in the dashboard, into the job log."""
        await self.write(Text(title, style="bold"))
        for line in lines:
            await self.write(Text(line))

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
        self.query_one("#sidebar", ChoiceList).focus()

    def action_copy_or_hint(self) -> None:
        """Ctrl-C copies the selected text, or says how to select and how to quit."""
        selected = self.screen.get_selected_text()
        if selected:
            self.copy_to_clipboard(selected)
            self.notify("Copied", timeout=2)
            return
        self.notify("Ctrl-Q quits. Drag to select text, then Ctrl-C copies (Cmd-C where the terminal passes it on; Option-drag and Cmd-C copy through the terminal itself).", timeout=5)
