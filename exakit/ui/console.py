"""The console renderer: one implementation, two palettes (plain and fancy).

Indentation is the legacy three-level scheme: a step header at two spaces,
an action at four (dim bullet), an outcome nested under it at six (tick,
warning, cross). Every menu in non-interactive mode returns its default and
says so, exactly as the shell did.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import IO

from exakit.domain.log import Log, NullLog
from exakit.domain.plan import Plan, Step, StepState

from .progress import ProgressState
from .menu import draw_menu, menu_key
from .spinner import Milestones, Spinner
from .widgets import FANCY, PLAIN, Option, Palette, term_cols, visible_len, wrap, wordmark_lines

SECTION_LABELS = {"datasets": "Sample data", "mcp_clients": "AI clients", "addons": "Add-ons",
                  "skills": "AI skills", "components": "Components"}


def step_label(step: Step | str) -> str:
    """What a step is called on screen: its label, else section and id."""
    if isinstance(step, str):
        return step
    return step.label or f"{SECTION_LABELS.get(step.section, step.section)}: {step.id}"


class ConsoleRenderer:
    """Draws to ``out``; reads from ``ask`` when there is a terminal to ask."""

    def __init__(self, *, palette: Palette, out: IO[str], interactive: bool, log: Log | None = None,
                 reader=None, home: str = "", err: IO[str] | None = None, keys=None) -> None:
        self.p = palette
        self.out = out
        self.err = err or sys.stderr
        self._key = keys            # a key reader (up/down/space/enter...) when the terminal gives one; else the numbered prompts
        self.interactive = interactive
        self.log = log or NullLog()
        self._read = reader or (lambda: sys.stdin.readline())
        self.home = home
        self._spin: Spinner | None = None
        self._transient = False                     # the live spinner is a working() line: the next line ends it
        self._step_t0 = 0.0
        self._steps_t0: dict[str, float] = {}       # the install steps' clocks, by id

    @property
    def fancy(self) -> bool:
        """True when the palette draws colour and glyphs."""
        return self.p.fancy

    # --- lines -------------------------------------------------------------------

    def _w(self, text: str = "") -> None:
        self._end_transient()
        self._clear_spinner_line()
        self.out.write(text + "\n")
        self.out.flush()

    def _clear_spinner_line(self) -> None:
        """Make room for a line while a spinner is alive: it redraws itself below."""
        if self._spin is not None:
            self.out.write("\r\x1b[K")

    def _end_transient(self) -> None:
        """A working() line gives way to whatever comes next."""
        if self._transient and self._spin is not None:
            self._spin.stop()
            self._spin = None
        self._transient = False

    def working(self, text: str) -> None:
        """Announce work in progress: a live line that the next line replaces; a plain line where nothing can be redrawn."""
        self.log.line("INFO", text)
        self._end_transient()
        if self.fancy and self.interactive and self._spin is None:
            self._spin = Spinner(self.out, self._spinner_template(text), self.p)
            self._spin.start()
            self._transient = True
            return
        if self._spin is None:
            self.out.write(f"    {self.p.dim}{self.p.bullet}{self.p.reset} {text}\n")
            self.out.flush()

    def text(self, line: str) -> None:
        """Write a line as is."""
        self._w(line)

    def banner(self, title: str, subtitle: str = "") -> None:
        """Draw the kit's banner: the wordmark in fancy mode, then the title and subtitle."""
        self._w()
        for line in wordmark_lines(self.p):
            self._w(line)
        if self.p.fancy:
            self._w()
        self._w(f"  {self.p.bold}{title}{self.p.reset}")
        if subtitle:
            self._w(f"  {self.p.dim}{subtitle}{self.p.reset}")
        self._w()

    def heading(self, text: str) -> None:
        """Write a step heading."""
        self._w(f"  {self.p.ok}{self.p.arrow}{self.p.reset} {text}")
        self.log.line("INFO", text)

    def info(self, text: str) -> None:
        """Write an informational line."""
        self._w(f"    {self.p.dim}{self.p.bullet}{self.p.reset} {text}")
        self.log.line("INFO", text)

    def ok(self, text: str) -> None:
        """Write a success line."""
        self._w(f"      {self.p.ok}{self.p.tick}{self.p.reset} {text}")
        self.log.line("OK", text)

    def warn(self, text: str) -> None:
        """Write a warning to the error stream and the log."""
        self._end_transient()
        self._clear_spinner_line()
        self.err.write(f"      {self.p.warn}!{self.p.reset} {text}\n")
        self.err.flush()
        self.log.line("WARN", text)

    def error(self, text: str) -> None:
        """Write an error to the error stream and the log."""
        self._end_transient()
        self._clear_spinner_line()
        self.err.write(f"      {self.p.err}{self.p.cross}{self.p.reset} {text}\n")
        self.err.flush()
        self.log.line("ERROR", text)

    def card(self, message: str, *, log_path: str | None = None, remedy: str | None = None) -> None:
        """The failure card, on stderr: a prominent cross header, the remedy, then a dim line to the log."""
        lines = ["", f"  {self.p.err}{self.p.cross} {self.p.bold}{message}{self.p.reset}"]
        if remedy:
            lines.append(f"    {self.p.dim}{self.p.bullet}{self.p.reset} Next: {remedy}")
        if log_path:
            lines.append(f"    {self.p.dim}{self.p.vb} Log: {log_path}{self.p.reset}")
        self.err.write("\n".join(lines) + "\n")
        self.err.flush()

    def rule(self) -> None:
        """Draw a horizontal rule."""
        width = min(76, max(8, term_cols() - 4))
        self._w()
        self._w(f"  {self.p.dim}{self.p.hr * width}{self.p.reset}")
        self._w()

    # --- panels ------------------------------------------------------------------

    def panel(self, title: str, lines: Sequence[str]) -> None:
        """A titled box sized to its widest line, capped and wrapped to the terminal."""
        width = max([len(title) + 1] + [visible_len(line) for line in lines]) + 2
        cap = max(24, term_cols() - 4) if self.interactive else width
        body = list(lines)
        if width > cap:
            width = cap
            body = []
            for line in lines:
                pieces = wrap(line, width - 4)
                body.append(pieces[0])
                body.extend("  " + piece for piece in pieces[1:])
        p = self.p
        head = f" {title} "
        fill = max(0, width - len(head) - 1)
        self._w(f"  {p.accent}{p.tl}{p.hr}{p.reset}{p.bold}{head}{p.reset}{p.accent}{p.hr * fill}{p.tr}{p.reset}")
        for line in body:
            pad = max(0, width - visible_len(line) - 2)
            self._w(f"  {p.accent}{p.vb}{p.reset} {line}{' ' * pad} {p.accent}{p.vb}{p.reset}")
        self._w(f"  {p.accent}{p.bl}{p.hr * width}{p.br}{p.reset}")

    def aside(self, title: str, lines: Sequence[str]) -> None:
        """What the screens show beside the log (a goodbye during an uninstall): a panel in the console."""
        self.panel(title, lines)

    def plan(self, plan: Plan) -> None:
        """The plan as a panel: one block per section, each item with its state and reason."""
        p = self.p
        lines: list[str] = []
        for section, steps in plan.by_section().items():
            lines.append(f"{SECTION_LABELS.get(section, section)}:")
            for step in steps:
                name = step.label or step.id
                if step.state is StepState.DONE:
                    mark = f"{p.ok}{p.tick}{p.reset}  {name} {p.dim}(already there){p.reset}"
                elif step.state is StepState.PENDING:
                    mark = f"{p.accent}+{p.reset}  {name}"
                elif step.state is StepState.FAILED:
                    mark = f"{p.err}{p.cross}{p.reset}  {name} {p.dim}(failed){p.reset}"
                else:
                    mark = f"{p.dim}-  {name} (skipped){p.reset}"
                lines.append(f"  {mark}")
                if step.reason:
                    lines.append(f"       {p.dim}{step.reason}{p.reset}")
        if not lines:
            lines.append("Nothing to do.")
        self.panel(plan.title, lines)

    # --- steps -------------------------------------------------------------------

    def _spinner_template(self, label: str) -> str:
        return f"{self.p.accent}{{frame}}{self.p.reset} {label}{{detail}} {self.p.dim}{{elapsed}}{self.p.reset}"

    @contextmanager
    def busy(self, label: str) -> Iterator[None]:
        """A spinner with the label and the time it has taken while a slow call runs; a log line elsewhere."""
        self.log.line("INFO", label)
        self._end_transient()
        if self.fancy and self.interactive and self._spin is None:
            self._spin = Spinner(self.out, self._spinner_template(label), self.p)
            self._spin.start()
            try:
                yield
            finally:
                self._spin.stop()
                self._spin = None
            return
        yield

    @contextmanager
    def progress(self, label: str, *, unit: str = "bytes") -> Iterator[ProgressState]:
        """The job's progress line while it runs (bytes, items or stages with the creep between them); plain lines elsewhere."""
        self.log.line("INFO", label)
        self._end_transient()
        state = ProgressState(label, unit=unit)
        if not (self.fancy and self.interactive):
            Milestones(self, state)
            yield state
            return
        own = self._spin is None
        spinner = self._spin = self._spin or Spinner(self.out, self._spinner_template(""), self.p)
        if own:
            spinner.start()
        spinner.states.append(state)
        try:
            yield state
        finally:
            spinner.states.remove(state)
            if own:
                spinner.stop()
                self._spin = None

    def step_begin(self, step: Step | str) -> None:
        """Announce a plan step as it starts: an install step as its heading, any other with a spinner."""
        if isinstance(step, Step) and step.section == "install":
            self._steps_t0[step.id] = time.monotonic()
            self.heading(step_label(step))
            return
        label = step_label(step)
        self._step_t0 = time.monotonic()
        if self.fancy and self.interactive:
            self._spin = Spinner(self.out, self._spinner_template(label), self.p)
            self._spin.start()
        else:
            self._w(f"  {self.p.arrow} {label}...")

    def step_end(self, step: Step | str, *, ok: bool = True, detail: str = "") -> None:
        """Close a plan step with its outcome and the time it took."""
        label = step_label(step)
        if isinstance(step, Step):
            ok = ok and step.state is not StepState.FAILED
            detail = detail or step.reason
        if self._spin and not (isinstance(step, Step) and step.section == "install"):
            self._spin.stop()
            self._spin = None
        t0 = self._steps_t0.pop(step.id, None) if isinstance(step, Step) else None
        elapsed = time.monotonic() - (self._step_t0 if t0 is None else t0)
        took = "<1s" if elapsed < 1 else f"{int(elapsed)}s"
        glyph = f"{self.p.ok}{self.p.tick}" if ok else f"{self.p.err}{self.p.cross}"
        extra = f" {self.p.dim}{detail}{self.p.reset}" if detail else ""
        tail = f" {self.p.dim}({took}){self.p.reset}" if self.fancy and ok else ""
        self._w(f"  {glyph}{self.p.reset} {label}{extra}{tail}")

    # --- questions -----------------------------------------------------------------

    def _ask(self, question: str, hint: str) -> str:
        self.out.write(f"    {self.p.ask}?{self.p.reset} {question} {self.p.dim}{hint}{self.p.reset} ")
        self.out.flush()
        return self._read().strip()

    def confirm(self, question: str, default: bool = True) -> bool:
        """Ask a yes/no question; the default answers when there is no terminal."""
        if not self.interactive:
            return default
        answer = self._ask(question, "[Y/n]" if default else "[y/N]")
        if not answer:
            return default
        return answer.lower() in ("y", "yes")

    def prompt(self, question: str, default: str = "") -> str:
        """Ask for a line of text; the default answers when there is no terminal."""
        if not self.interactive:
            return default
        answer = self._ask(question, f"[{default}]" if default else "")
        return answer or default

    def select(self, title: str, options: Sequence[Option], default: int = 1) -> str | None:
        """A single choice: arrow keys and Enter in a terminal, else a numbered prompt. None when the reader backs out."""
        if self.interactive and self._key is not None:
            self.heading(title)
            picked = self._menu(options, {options[default - 1].id} if 1 <= default <= len(options) else set(), single=True)
            return next(iter(picked), None) if picked is not None else None
        self.heading(title)
        for number, option in enumerate(options, start=1):
            hint = f"  {self.p.dim}{option.hint}{self.p.reset}" if option.hint else ""
            self._w(f"      {self.p.accent}{number}.{self.p.reset} {option.label}{hint}")
        self._w(f"      {self.p.dim}Enter the number (Enter keeps {default}, 0 backs out){self.p.reset}")
        if not self.interactive:
            self.info(f"No terminal: keeping the default ({default}).")
            return options[default - 1].id if 1 <= default <= len(options) else None
        answer = self.prompt("Choice", str(default))
        if not answer.isdigit() or not 1 <= int(answer) <= len(options):
            return None
        return options[int(answer) - 1].id

    def checkboxes(self, title: str, options: Sequence[Option], defaults: Sequence[str]) -> list[str]:
        """A multiple choice: arrows move, Space toggles, Enter continues in a terminal; else numbers (``1,3``), ``a`` for all."""
        self.heading(title)
        chosen = set(defaults)
        if self.interactive and self._key is not None:
            picked = self._menu(options, {o.id for o in options if o.id in chosen and not o.disabled}, single=False)
            return [o.id for o in options if o.id in (picked if picked is not None else chosen) and not o.disabled]
        for number, option in enumerate(options, start=1):
            box = "[x]" if option.id in chosen else "[ ]"
            if option.disabled:
                box = f"{self.p.dim}[-]"
            self._w(f"      {self.p.accent}{number}.{self.p.reset} {box} {option.label}{self.p.reset}")
        if not self.interactive:
            self.info("No terminal: keeping the pre-selected defaults.")
            return [o.id for o in options if o.id in chosen and not o.disabled]
        answer = self.prompt("Numbers to select (a = all, Enter keeps the ticks)", "")
        if answer.lower() == "a":
            return [o.id for o in options if not o.disabled]
        if answer:
            picked = {int(t) for t in answer.replace(" ", "").split(",") if t.isdigit()}
            return [o.id for n, o in enumerate(options, start=1) if n in picked and not o.disabled]
        return [o.id for o in options if o.id in chosen and not o.disabled]


    # --- the arrow-key menu ----------------------------------------------------------

    def _menu(self, options: Sequence[Option], chosen: set[str], *, single: bool) -> set[str] | None:
        """Draw the options with a cursor and redraw on every key; the chosen ids on Enter, None on Esc."""
        cursor = next((i for i, o in enumerate(options) if o.id in chosen), 0)
        hint = "Up/Down move, Enter chooses, Esc backs out" if single else "Up/Down move, Space toggles, Enter continues, a all, n none"
        self.out.write("\x1b[?25l")
        try:
            draw_menu(self.out, self.p, options, chosen, cursor, hint, single, first=True)
            while True:
                action, cursor = menu_key(self._key(), options, chosen, cursor, single)
                if action == "enter":
                    if single and not options[cursor].disabled:
                        return {options[cursor].id}
                    return chosen
                if action == "esc":
                    return None
                draw_menu(self.out, self.p, options, chosen, cursor, hint, single, first=False)
        finally:
            self.out.write("\x1b[?25h")
            self.out.flush()

def plain(out: IO[str] = sys.stdout, *, interactive: bool = False, log: Log | None = None) -> ConsoleRenderer:
    """A renderer without colour or glyphs."""
    return ConsoleRenderer(palette=PLAIN, out=out, interactive=interactive, log=log)


def fancy(out: IO[str] = sys.stdout, *, interactive: bool = True, log: Log | None = None) -> ConsoleRenderer:
    """True when the palette draws colour and glyphs."""
    return ConsoleRenderer(palette=FANCY, out=out, interactive=interactive, log=log)
