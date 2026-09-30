"""The renderer behind ``--json``: nothing reaches stdout, everything goes to the log.

Menus answer with their defaults and questions with their default answer,
so a use case never blocks under ``--json``; ``run_plan`` refuses to apply
without ``--yes`` before any question would be asked.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from exakit.adapters.fs.log import Log, NullLog
from exakit.domain.plan import Plan, Step

from .widgets import Option


class SilentRenderer:
    interactive = False
    fancy = False

    def __init__(self, log: Log | None = None) -> None:
        self.log = log or NullLog()

    def text(self, line: str) -> None:
        self.log.line("INFO", line)

    def banner(self, title: str, subtitle: str = "") -> None:
        self.log.line("INFO", title)

    def heading(self, text: str) -> None:
        self.log.line("INFO", text)

    def info(self, text: str) -> None:
        self.log.line("INFO", text)

    def ok(self, text: str) -> None:
        self.log.line("OK", text)

    def warn(self, text: str) -> None:
        self.log.line("WARN", text)

    def error(self, text: str) -> None:
        self.log.line("ERROR", text)

    def card(self, message: str, *, log_path: str | None = None, remedy: str | None = None) -> None:
        self.log.line("FATAL", message)

    def rule(self) -> None:
        return None

    def panel(self, title: str, lines: Sequence[str]) -> None:
        self.log.line("INFO", title)

    def plan(self, plan: Plan) -> None:
        self.log.line("INFO", f"{plan.title}: {len(plan.pending())} pending")

    def step_begin(self, step: Step | str) -> None:
        self.log.line("INFO", f"begin {step if isinstance(step, str) else step.id}")

    def step_end(self, step: Step | str, *, ok: bool = True, detail: str = "") -> None:
        self.log.line("INFO", f"end {step if isinstance(step, str) else step.id} {detail}".rstrip())

    def confirm(self, question: str, default: bool = True) -> bool:
        return default

    def prompt(self, question: str, default: str = "") -> str:
        return default

    def select(self, title: str, options: Sequence[Option], default: int = 1) -> str | None:
        return options[default - 1].id if 1 <= default <= len(options) else None

    def checkboxes(self, title: str, options: Sequence[Option], defaults: Sequence[str]) -> list[str]:
        return [o.id for o in options if o.id in set(defaults) and not o.disabled]

    @contextmanager
    def busy(self, label: str) -> Iterator[None]:
        self.log.line("INFO", label)
        yield
