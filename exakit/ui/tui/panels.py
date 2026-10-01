"""The widgets of the kit's screens: the wordmark header, the plan panel, the log with its live progress rows."""

from __future__ import annotations

import time

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from exakit.domain.plan import Plan, Step, StepState
from exakit.ui.console import step_label
from exakit.ui.progress import ProgressState, elapsed_text, progress_parts
from exakit.ui.spinner import SPIN_FRAMES
from exakit.ui.widgets import WORDMARK_E, WORDMARK_REST, WORDMARK_X_LEFT, WORDMARK_X_RIGHT

ACCENT = "green"
WORDMARK_WIDTH = 70        # columns the wordmark needs; narrower terminals get the title alone
GLYPHS = {StepState.DONE: ("✓", ACCENT), StepState.PENDING: ("·", "dim"), StepState.SKIPPED: ("-", "dim"), StepState.FAILED: ("✗", "red")}
STYLES = {"accent": ACCENT, "dim": "dim", "bold": "bold", "": ""}


def step_key(step: Step | str) -> str:
    """The key a step's row is kept under."""
    return step if isinstance(step, str) else f"{step.section}/{step.id}"


class WordmarkHeader(Static):
    """The EXASOL wordmark with its green X, then the title, then the subtitle on its own line."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__(id="header")
        self.title_text = title
        self.subtitle_text = subtitle

    def on_mount(self) -> None:
        """Draw the header once mounted."""
        self.redraw()

    def on_resize(self) -> None:
        """Redraw: the wordmark needs 70 columns, a narrower terminal gets the title alone."""
        self.redraw()

    def set_title(self, title: str, subtitle: str = "") -> None:
        """Replace the title and the subtitle."""
        self.title_text, self.subtitle_text = title, subtitle
        self.redraw()

    def redraw(self) -> None:
        """Compose the header text."""
        text = Text()
        if self.app.size.width >= WORDMARK_WIDTH:
            for e, xl, xr, rest in zip(WORDMARK_E, WORDMARK_X_LEFT, WORDMARK_X_RIGHT, WORDMARK_REST, strict=True):
                text.append(e, style="bold").append(xl, style=f"bold {ACCENT}").append(xr + rest + "\n", style="bold")
        text.append(self.title_text, style="bold")
        if self.subtitle_text:
            text.append("\n" + self.subtitle_text, style="dim")
        self.update(text)


def _aside_style(line: str) -> str:
    """An address and a command stand out; indented notes are dim."""
    if "@" in line or line.lstrip().startswith(("curl ", "irm ")):
        return f"bold {ACCENT}"
    return "dim" if line.startswith("  ") else ""


class PlanPanel(VerticalScroll):
    """One row per step: the state glyph, the label, the detail or the time it took."""

    def __init__(self) -> None:
        super().__init__(id="plan")
        self.border_title = "Plan"
        self.rows: dict[str, Static] = {}
        self.texts: dict[str, Text] = {}          # what each row shows, for the tests and the transcript
        self.started: dict[str, float] = {}

    def set_plan(self, plan: Plan) -> None:
        """Replace every row with the plan's steps."""
        self.border_title = plan.title or "Plan"
        self.remove_children()
        self.rows.clear()
        for step in plan.steps:
            text = self._row_text(step, *GLYPHS[step.state], step.reason)
            row = Static(text)
            self.rows[step_key(step)], self.texts[step_key(step)] = row, text
            self.mount(row)

    def _row_text(self, step: Step | str, glyph: str, style: str, detail: str) -> Text:
        text = Text.assemble((glyph, style), " ", step_label(step))
        if detail:
            text.append(f"  {detail}", style="dim")
        return text

    def set_aside(self, title: str, lines: list[str]) -> None:
        """Replace the rows with free text under a title (the sign-off during an uninstall)."""
        self.border_title = title
        self.remove_children()
        self.rows.clear()
        self.texts.clear()
        text = Text()
        for line in lines:
            text.append(line + "\n", style=_aside_style(line))
        self.mount(Static(text))

    def begin(self, step: Step | str) -> None:
        """Mark a step as running and start its clock."""
        self.started[step_key(step)] = time.monotonic()
        self._set(step, "▸", ACCENT, "running")

    def end(self, step: Step | str, *, ok: bool, detail: str) -> None:
        """Mark a step finished with its outcome and the time it took."""
        took = elapsed_text(time.monotonic() - self.started.pop(step_key(step), time.monotonic())) or "<1s"
        self._set(step, "✓" if ok else "✗", ACCENT if ok else "red", detail or f"({took})")

    def _set(self, step: Step | str, glyph: str, style: str, detail: str) -> None:
        key = step_key(step)
        row = self.rows.get(key)
        if row is None:
            row = Static()
            self.rows[key] = row
            self.mount(row)
        self.texts[key] = self._row_text(step, glyph, style, detail)
        row.update(self.texts[key])
        row.scroll_visible()


class ProgressRow(Static):
    """A live line under the text that announced the job: the spinner, the phase, the bar, the percent, the time."""

    def __init__(self, state: ProgressState) -> None:
        super().__init__(classes="live")
        self.state = state
        self._frame = 0

    def on_mount(self) -> None:
        """Tick ten times a second while the job runs."""
        self.set_interval(0.1, self.tick)
        self.tick()

    def tick(self) -> None:
        """Redraw from the job's state."""
        self._frame += 1
        parts = progress_parts(self.state, frame=SPIN_FRAMES[self._frame % len(SPIN_FRAMES)], cols=max(40, self.size.width or 80), fancy=True)
        self.update(Text.assemble(*((text, STYLES[style]) for text, style in parts)))


class Loader(Static):
    """A spinner with a word at the right of a row while something refreshes; empty when idle."""

    def __init__(self, label: str = "Refreshing…") -> None:
        super().__init__("", id="loader")
        self.label = label
        self.active = False
        self._frame = 0
        self._t0 = 0.0

    def on_mount(self) -> None:
        """Tick while active."""
        self.set_interval(0.1, self._tick)

    def start(self) -> None:
        """Show the spinner."""
        self.active = True
        self._t0 = time.monotonic()
        self._tick()

    def stop(self) -> None:
        """Hide it."""
        self.active = False
        self.update("")

    def _tick(self) -> None:
        if not self.active:
            return
        self._frame += 1
        took = elapsed_text(time.monotonic() - self._t0)
        self.update(Text.assemble((SPIN_FRAMES[self._frame % len(SPIN_FRAMES)], ACCENT), f" {self.label}", (f" {took}" if took else "", "dim")))


class LogPane(VerticalScroll):
    """The lines of the run, in order; a running job gets a live row right under the line that announced it."""

    def __init__(self) -> None:
        super().__init__(id="log")
        self.lines: list[Text] = []

    def write(self, text: Text) -> None:
        """Append a line, above any live rows, and keep the end in view."""
        self.lines.append(text)
        row = Static(text)
        live = self.query(ProgressRow)
        if live:
            self.mount(row, before=live.first())
        else:
            self.mount(row)
        self.scroll_end(animate=False)

    def live_begin(self, state: ProgressState) -> ProgressRow:
        """Start a live progress row at the end."""
        row = ProgressRow(state)
        self.mount(row)
        self.scroll_end(animate=False)
        return row

    async def live_end(self, row: ProgressRow) -> None:
        """The job finished: its live row goes."""
        await row.remove()
