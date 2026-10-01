"""The Renderer the command sees inside the app: every call is handed to the app's thread, and mirrored to a plain transcript."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from rich.text import Text

from exakit.domain.plan import Plan, Step, StepState
from exakit.ui.console import ConsoleRenderer
from exakit.ui.progress import ProgressState
from exakit.ui.widgets import Option

from .app import KitApp
from .screens import CheckboxScreen, ConfirmScreen, PromptScreen, SelectScreen

STYLES = {"info": ("•", "dim"), "ok": ("✓", "green"), "warn": ("!", "yellow"), "error": ("✗", "bold red")}


class TuiRenderer:
    """Implements the Renderer protocol over a running KitApp, from the worker thread."""

    interactive = True
    fancy = True

    def __init__(self, app: KitApp, mirror: ConsoleRenderer) -> None:
        self.app = app
        self.mirror = mirror        # the plain transcript (and the log): what the console would have printed

    def _call(self, fn: Callable, *args, **kwargs):
        return self.app.call_from_thread(fn, *args, **kwargs)

    def _line(self, kind: str, text: str) -> None:
        glyph, style = STYLES[kind]
        self._call(self.app.write, Text.assemble((glyph, style), " ", text))

    # --- lines -------------------------------------------------------------------------

    def text(self, line: str) -> None:
        """A line as is."""
        self.mirror.text(line)
        self._call(self.app.write, Text(line))

    def banner(self, title: str, subtitle: str = "") -> None:
        """The header's title and subtitle."""
        self.mirror.banner(title, subtitle)
        self._call(self.app.set_title, title, subtitle)

    def heading(self, text: str) -> None:
        """A bold line, with a blank line before it."""
        self.mirror.heading(text)
        self._call(self.app.write, Text(""))
        self._call(self.app.write, Text(text, style="bold"))

    def info(self, text: str) -> None:
        """An informational line."""
        self.mirror.info(text)
        self._line("info", text)

    def ok(self, text: str) -> None:
        """A success line."""
        self.mirror.ok(text)
        self._line("ok", text)

    def warn(self, text: str) -> None:
        """A warning."""
        self.mirror.warn(text)
        self._line("warn", text)

    def error(self, text: str) -> None:
        """An error."""
        self.mirror.error(text)
        self._line("error", text)

    def card(self, message: str, *, log_path: str | None = None, remedy: str | None = None) -> None:
        """The failure card."""
        self.mirror.card(message, log_path=log_path, remedy=remedy)
        self._call(self.app.write, Text.assemble(("✗ ", "bold red"), (message, "bold")))
        if remedy:
            self._call(self.app.write, Text(f"  Fix: {remedy}"))
        if log_path:
            self._call(self.app.write, Text(f"  Log: {log_path}", style="dim"))

    def rule(self) -> None:
        """A separator."""
        self.mirror.rule()
        self._call(self.app.write, Text("─" * 60, style="dim"))

    def panel(self, title: str, lines: Sequence[str]) -> None:
        """A titled block of lines."""
        self.mirror.panel(title, lines)
        self._call(self.app.write, Text(title, style="bold"))
        for line in lines:
            self._call(self.app.write, Text(f"  {line}"))

    # --- the plan and its steps --------------------------------------------------------------

    def plan(self, plan: Plan) -> None:
        """The plan panel."""
        self.mirror.plan(plan)
        self._call(self.app.set_plan, plan)

    def step_begin(self, step: Step | str) -> None:
        """A step starts: the plan row runs, and an install step's heading goes into the log."""
        self.mirror.step_begin(step)
        if isinstance(step, Step) and step.section == "install":
            self._call(self.app.write, Text(""))
            self._call(self.app.write, Text(step.label or step.id, style="bold"))
        self._call(self.app.step_begin, step)

    def step_end(self, step: Step | str, *, ok: bool = True, detail: str = "") -> None:
        """A step ends."""
        self.mirror.step_end(step, ok=ok, detail=detail)
        if isinstance(step, Step):
            ok, detail = ok and step.state is not StepState.FAILED, detail or step.reason
        self._call(self.app.step_end, step, ok=ok, detail=detail)

    # --- questions ------------------------------------------------------------------------------

    def confirm(self, question: str, default: bool = True) -> bool:
        """A yes/no on a modal screen."""
        answer = bool(self._call(self.app.ask, ConfirmScreen(question, default)))
        self.mirror.text(f"? {question} {'yes' if answer else 'no'}")
        return answer

    def prompt(self, question: str, default: str = "") -> str:
        """A line of text on a modal screen."""
        answer = str(self._call(self.app.ask, PromptScreen(question, default)))
        self.mirror.text(f"? {question} {answer}")
        return answer

    def select(self, title: str, options: Sequence[Option], default: int = 1) -> str | None:
        """One choice on a modal screen."""
        answer = self._call(self.app.ask, SelectScreen(title, options, default))
        self.mirror.text(f"? {title} {answer if answer is not None else '(back)'}")
        return answer

    def checkboxes(self, title: str, options: Sequence[Option], defaults: Sequence[str]) -> list[str]:
        """A tick list on a modal screen."""
        answer = list(self._call(self.app.ask, CheckboxScreen(title, options, defaults)))
        self.mirror.text(f"? {title} {', '.join(answer) or 'none'}")
        return answer

    # --- the live rows ----------------------------------------------------------------------------

    @contextmanager
    def busy(self, label: str) -> Iterator[None]:
        """A live row with the label and the time so far, right under the text, while a slow call runs."""
        with self.progress(label, unit="percent"):
            yield

    @contextmanager
    def progress(self, label: str, *, unit: str = "bytes") -> Iterator[ProgressState]:
        """A live progress row under the text that announced the job; the transcript gets the plain lines."""
        with self.mirror.progress(label, unit=unit) as state:
            row = self._call(self.app.live_begin, state)
            try:
                yield state
            finally:
                self._call(self.app.live_end, row)
