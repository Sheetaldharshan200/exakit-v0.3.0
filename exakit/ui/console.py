"""The console renderer: one implementation, two palettes (plain and fancy).

Indentation is the legacy three-level scheme: a step header at two spaces,
an action at four (dim bullet), an outcome nested under it at six (tick,
warning, cross). Every menu in non-interactive mode returns its default and
says so, exactly as the shell did.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Sequence
from typing import IO

from exakit.adapters.fs.log import Log, NullLog
from exakit.domain.plan import Plan, Step, StepState

from .widgets import FANCY, PLAIN, Option, Palette, term_cols, visible_len, wrap

SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SECTION_LABELS = {"datasets": "Sample data", "mcp_clients": "AI clients", "addons": "Add-ons",
                  "skills": "AI skills", "components": "Components"}


class ConsoleRenderer:
    """Draws to ``out``; reads from ``ask`` when there is a terminal to ask."""

    def __init__(self, *, palette: Palette, out: IO[str], interactive: bool, log: Log | None = None,
                 reader=None, home: str = "") -> None:
        self.p = palette
        self.out = out
        self.interactive = interactive
        self.log = log or NullLog()
        self._read = reader or (lambda: sys.stdin.readline())
        self.home = home
        self._spin: _Spinner | None = None
        self._step_t0 = 0.0

    @property
    def fancy(self) -> bool:
        return self.p.fancy

    # --- lines -------------------------------------------------------------------

    def _w(self, text: str = "") -> None:
        self.out.write(text + "\n")
        self.out.flush()

    def text(self, line: str) -> None:
        self._w(line)

    def banner(self, title: str, subtitle: str = "") -> None:
        self._w()
        self._w(f"  {self.p.bold}{title}{self.p.reset}")
        if subtitle:
            self._w(f"  {self.p.dim}{subtitle}{self.p.reset}")
        self._w()

    def heading(self, text: str) -> None:
        self._w(f"  {self.p.ok}{self.p.arrow}{self.p.reset} {text}")
        self.log.line("INFO", text)

    def info(self, text: str) -> None:
        self._w(f"    {self.p.dim}{self.p.bullet}{self.p.reset} {text}")
        self.log.line("INFO", text)

    def ok(self, text: str) -> None:
        self._w(f"      {self.p.ok}{self.p.tick}{self.p.reset} {text}")
        self.log.line("OK", text)

    def warn(self, text: str) -> None:
        sys.stderr.write(f"      {self.p.warn}!{self.p.reset} {text}\n")
        sys.stderr.flush()
        self.log.line("WARN", text)

    def error(self, text: str) -> None:
        sys.stderr.write(f"      {self.p.err}{self.p.cross}{self.p.reset} {text}\n")
        sys.stderr.flush()
        self.log.line("ERROR", text)

    def card(self, message: str, *, log_path: str | None = None) -> None:
        """The failure card: a prominent cross header, then a dim line to the log."""
        self._w()
        self._w(f"  {self.p.err}{self.p.cross} {self.p.bold}{message}{self.p.reset}")
        if log_path:
            self._w(f"    {self.p.dim}{self.p.vb} Log: {log_path}{self.p.reset}")

    def rule(self) -> None:
        width = min(76, max(8, term_cols() - 4))
        self._w()
        self._w(f"  {self.p.dim}{self.p.hr * width}{self.p.reset}")
        self._w()

    # --- panels ------------------------------------------------------------------

    def panel(self, title: str, lines: Sequence[str]) -> None:
        """A titled box sized to its widest line, capped and wrapped to the terminal."""
        width = max([len(title) + 1] + [visible_len(l) for l in lines]) + 2
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

    def plan(self, plan: Plan) -> None:
        """The plan as a panel: one block per section, each item with its state and reason."""
        p = self.p
        lines: list[str] = []
        for section, steps in plan.by_section().items():
            lines.append(f"{SECTION_LABELS.get(section, section)}:")
            for step in steps:
                if step.state is StepState.DONE:
                    mark = f"{p.ok}{p.tick}{p.reset}  {step.id} {p.dim}(already there){p.reset}"
                elif step.state is StepState.PENDING:
                    mark = f"{p.accent}+{p.reset}  {step.id}"
                elif step.state is StepState.FAILED:
                    mark = f"{p.err}{p.cross}{p.reset}  {step.id} {p.dim}(failed){p.reset}"
                else:
                    mark = f"{p.dim}-  {step.id} (skipped){p.reset}"
                lines.append(f"  {mark}")
                if step.reason:
                    lines.append(f"       {p.dim}{step.reason}{p.reset}")
        if not lines:
            lines.append("Nothing to do.")
        self.panel(plan.title, lines)

    # --- steps -------------------------------------------------------------------

    def step_begin(self, step: Step | str) -> None:
        label = step if isinstance(step, str) else f"{SECTION_LABELS.get(step.section, step.section)}: {step.id}"
        self._step_t0 = time.monotonic()
        if self.fancy and self.interactive:
            self._spin = _Spinner(self.out, f"{self.p.accent}{{frame}}{self.p.reset} {label}")
            self._spin.start()
        else:
            self._w(f"  {self.p.arrow} {label}...")

    def step_end(self, step: Step | str, *, ok: bool = True, detail: str = "") -> None:
        label = step if isinstance(step, str) else f"{SECTION_LABELS.get(step.section, step.section)}: {step.id}"
        if isinstance(step, Step):
            ok = step.state is not StepState.FAILED
            detail = detail or step.reason
        if self._spin:
            self._spin.stop()
            self._spin = None
        elapsed = time.monotonic() - self._step_t0
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
        if not self.interactive:
            return default
        answer = self._ask(question, "[Y/n]" if default else "[y/N]")
        if not answer:
            return default
        return answer.lower() in ("y", "yes")

    def prompt(self, question: str, default: str = "") -> str:
        if not self.interactive:
            return default
        answer = self._ask(question, f"[{default}]" if default else "")
        return answer or default

    def select(self, title: str, options: Sequence[Option], default: int = 1) -> str | None:
        """A numbered single choice. Returns the chosen option id, or None when the reader backs out."""
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
        """A multiple choice by numbers (``1,3``), ``a`` for all, empty for the defaults."""
        self.heading(title)
        chosen = set(defaults)
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


class _Spinner:
    """Redraws one line on a thread until stopped. Only one is ever alive."""

    def __init__(self, out: IO[str], template: str) -> None:
        self.out = out
        self.template = template
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.out.write("\x1b[?25l")
        self._thread.start()

    def _run(self) -> None:
        i = 0
        while not self._stop.is_set():
            self.out.write("\r\x1b[K  " + self.template.format(frame=SPIN_FRAMES[i % len(SPIN_FRAMES)]))
            self.out.flush()
            i += 1
            self._stop.wait(0.1)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        self.out.write("\r\x1b[K\x1b[?25h")
        self.out.flush()


def plain(out: IO[str] = sys.stdout, *, interactive: bool = False, log: Log | None = None) -> ConsoleRenderer:
    return ConsoleRenderer(palette=PLAIN, out=out, interactive=interactive, log=log)


def fancy(out: IO[str] = sys.stdout, *, interactive: bool = True, log: Log | None = None) -> ConsoleRenderer:
    return ConsoleRenderer(palette=FANCY, out=out, interactive=interactive, log=log)
