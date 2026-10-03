"""The kit's full-screen app: the command runs in a worker thread, the screens draw on the main thread, in the terminal's own colours."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen

from exakit.domain.errors import ExakitError
from exakit.domain.plan import Plan, Step
from exakit.domain.result import Result
from exakit.ui.progress import ProgressState

from .copying import CopyKeys
from .panels import LogPane, PlanPanel, ProgressRow, WordmarkHeader


class KitApp(CopyKeys, App[None]):
    """Header, plan, log; ``job`` runs in a thread once the app is mounted."""

    CSS_PATH = "app.tcss"
    BINDINGS = [Binding("ctrl+q", "request_quit", "Quit"), Binding("ctrl+c", "copy_or_hint", "Copy", show=False, priority=True),
                Binding("super+c", "copy_or_hint", "Copy", show=False, priority=True),
                Binding("enter", "close", "Close when finished", show=False), Binding("q", "close", "Close", show=False)]

    def __init__(self, *, title: str, subtitle: str = "", job: Callable[[], Result] | None = None,
                 copier: Callable[[str], bool] | None = None) -> None:
        super().__init__(ansi_color=True)
        self.copier = copier
        self.title_text = title
        self.subtitle_text = subtitle
        self.job = job
        self.done = False
        self.final = ""
        self._outcome: tuple[str, Any] | None = None

    def on_resize(self) -> None:
        """A height change alone does not resize the header: redraw it, so the wordmark comes and goes with the rows."""
        for header in self.query(WordmarkHeader):
            header.redraw()

    # --- layout ---------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """The wordmark header, then the plan beside the log."""
        yield WordmarkHeader(self.title_text, self.subtitle_text)
        with Horizontal(id="body"):
            yield PlanPanel()
            yield LogPane()

    def on_mount(self) -> None:
        """Start the command in a worker thread."""
        if self.job is not None:
            self.run_worker(self._work, thread=True, exit_on_error=False, name="command")

    def _work(self) -> None:
        try:
            self._outcome = ("result", self.job())      # type: ignore[misc]
        except ExakitError as err:
            self._outcome = ("error", err)
        except BaseException as err:    # carried to the main thread and re-raised there
            self._outcome = ("crash", err)
        self.call_from_thread(self._finished)

    def _finished(self) -> None:
        self.done = True
        kind = self._outcome[0] if self._outcome else "crash"
        self.final = "Finished - press Enter to close" if kind == "result" else "Stopped - press Enter to close (the details follow)"
        self.write(Text(""))
        self.write(Text(self.final, style="bold"))

    # --- what the worker asks for (every call arrives through call_from_thread) ----------------

    def write(self, text: Text) -> None:
        """Append a line to the log."""
        self.query_one(LogPane).write(text)

    def set_title(self, title: str, subtitle: str = "") -> None:
        """Replace the header's title and subtitle."""
        self.query_one(WordmarkHeader).set_title(title, subtitle)

    def set_plan(self, plan: Plan) -> None:
        """Show a plan in the plan panel."""
        self.query_one(PlanPanel).set_plan(plan)

    def set_aside(self, title: str, lines: list[str]) -> None:
        """Show free text in the left panel instead of a plan."""
        self.query_one(PlanPanel).set_aside(title, lines)

    def step_begin(self, step: Step | str) -> None:
        """A step started."""
        self.query_one(PlanPanel).begin(step)

    def step_end(self, step: Step | str, *, ok: bool, detail: str) -> None:
        """A step finished."""
        self.query_one(PlanPanel).end(step, ok=ok, detail=detail)

    def live_begin(self, state: ProgressState) -> ProgressRow:
        """A job started: its live row under the text."""
        return self.query_one(LogPane).live_begin(state)

    async def live_end(self, row: ProgressRow) -> None:
        """The job finished: the live row goes."""
        await self.query_one(LogPane).live_end(row)

    async def ask(self, screen: ModalScreen) -> Any:
        """Show a modal question and wait for its answer."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.push_screen(screen, callback=future.set_result)
        return await future

    # --- keys ---------------------------------------------------------------------------------

    def action_close(self) -> None:
        """Enter or q close the app once the command finished."""
        if self.done:
            self.exit()

    def action_request_quit(self) -> None:
        """Ctrl-Q: leave now; the process exits 130 as it did without the screens."""
        if not self.done:
            self._outcome = ("interrupt", None)
        self.exit()

    def outcome(self) -> Result:
        """The job's Result; its ExakitError raised; KeyboardInterrupt when the app was quit early."""
        kind, value = self._outcome or ("interrupt", None)
        if kind == "result":
            return value
        if kind == "interrupt":
            raise KeyboardInterrupt
        raise value
