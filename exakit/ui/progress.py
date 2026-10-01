"""One progress state for every long job, and the one line that draws it.

The legacy kit's rule, kept: milestones are the truth (the bar never claims a stage the job has
not reached), and the time between two milestones is filled in at the pace that stage usually
takes, capped one point below the next milestone. The line is laid out in cells across the
terminal's width - phase, bar, percent, elapsed - so nothing shuffles sideways as the words change.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

EIGHTHS = " ▏▎▍▌▋▊▉"
UNITS = ("bytes", "items", "percent", "spinner")      # spinner: a working line, the label and the time so far, no bar


def human_size(count: int) -> str:
    """``118 KB``, ``12.4 MB``, ``1.2 GB``."""
    if count < 1024 * 1024:
        return f"{max(1, count // 1024)} KB"
    if count < 1024 * 1024 * 1024:
        return f"{count / (1024 * 1024):.1f} MB"
    return f"{count / (1024 * 1024 * 1024):.2f} GB"


def creep(pct: int, ceiling: int, seconds: float, elapsed: float) -> int:
    """Where the bar sits now, between the stage reached and the next one; never the next one itself."""
    span = ceiling - pct
    if span <= 0 or seconds <= 0:
        return pct
    step = int(span * elapsed / seconds + 1e-6)      # 9.999999s of a 10s stage is the whole stage
    return pct + max(0, min(step, span - 1))


@dataclass
class ProgressState:
    """What a job reports: bytes or items done of a total, or the stage it reached (percent mode)."""

    label: str
    unit: str = "bytes"
    done: int = 0
    total: int | None = None
    pct: int = 0
    ceiling: int = 0
    seconds: float = 0.0
    phase: str = ""
    shown: int = 0
    t0: float = field(default_factory=time.monotonic)
    segment_t0: float = field(default_factory=time.monotonic)
    on_change: Callable[[ProgressState], None] | None = None

    def __call__(self, done: int, total: int | None = None) -> None:
        """The reporter is callable: ``report(done, total)``."""
        self.update(done, total)

    def update(self, done: int, total: int | None = None) -> None:
        """Bytes or items landed so far."""
        self.done, self.total = done, total
        if total:
            self.pct = self.ceiling = min(100, done * 100 // total)
        if self.on_change:
            self.on_change(self)

    def stage(self, pct: int, ceiling: int, seconds: float, phase: str) -> None:
        """The job reached a stage: where it is, where the next one sits, how long this one usually takes."""
        if pct > self.pct or self.ceiling == 0:
            self.pct = max(pct, self.pct)
        self.ceiling, self.seconds, self.phase = max(ceiling, self.pct), seconds, phase
        self.segment_t0 = time.monotonic()
        if self.on_change:
            self.on_change(self)

    def set_phase(self, phase: str) -> None:
        """Change the words without moving the bar or restarting the stage's clock."""
        self.phase = phase
        if self.on_change:
            self.on_change(self)

    def position(self, now: float | None = None) -> int:
        """The percent to draw now: the stage reached plus the creep; it never walks backwards."""
        now = time.monotonic() if now is None else now
        at = creep(self.pct, self.ceiling, self.seconds, now - self.segment_t0) if self.unit == "percent" else self.pct
        self.shown = max(self.shown, min(100, at))
        return self.shown

    def text(self) -> str:
        """The phase cell: the label and, for bytes or items, the count so far."""
        head = self.phase or self.label
        if self.unit == "bytes" and self.done:
            return f"{head} · {human_size(self.done)}{'/' + human_size(self.total) if self.total else ''}"
        if self.unit == "items" and self.total:
            return f"{head} · {self.done}/{self.total}"
        return head

    def elapsed(self, now: float | None = None) -> float:
        """Seconds since the job began."""
        return (time.monotonic() if now is None else now) - self.t0


def bar_cells(pct: int, width: int, *, fancy: bool) -> tuple[str, str, str]:
    """(full, head, empty) for a bar of ``width`` cells; fancy mode draws eighths at the frontier."""
    if not fancy:
        full = min(width, pct * width // 100)
        return "#" * full, "", "." * (width - full)
    units = pct * width * 8 // 100
    full, rem = divmod(units, 8)
    if full >= width:
        return "█" * width, "", ""
    head = EIGHTHS[rem] if rem else ""
    return "█" * full, head, "░" * (width - full - (1 if head else 0))


def layout(cols: int) -> tuple[int, int, int, int, int]:
    """(text, gap, bar, percent, elapsed) cell widths for ``cols``: the bar 40% (at most 40 cells), the numbers 10% each (floored), the phase the rest."""
    avail = max(24, min(112, cols - 9))
    bar, num, el = min(40, max(8, avail * 40 // 100)), max(5, avail * 10 // 100), max(7, avail * 10 // 100)
    text = max(8, avail - bar - num - el - 1)
    return text, max(1, avail - text - bar - num - el), bar, num, el


def elapsed_text(seconds: float) -> str:
    """``12s`` or ``1m 05s``; nothing in the first two seconds."""
    if seconds < 2:
        return ""
    whole = int(seconds)
    return f"{whole}s" if whole < 60 else f"{whole // 60}m {whole % 60:02d}s"


def progress_parts(state: ProgressState, *, frame: str, cols: int, fancy: bool, now: float | None = None) -> list[tuple[str, str]]:
    """The line as (text, style) parts; styles are accent, dim, bold or empty."""
    now = time.monotonic() if now is None else now
    if state.unit == "spinner":
        took = elapsed_text(state.elapsed(now))
        return [(frame, "accent"), (" " + state.text(), ""), ("  " + took if took else "", "dim")]
    text_w, gap, bar_w, num_w, el_w = layout(cols)
    pct = state.position(now)
    phase = state.text()
    if len(phase) > text_w - 1:
        phase = phase[: max(0, text_w - 2)] + "…"
    full, head, empty = bar_cells(pct, bar_w, fancy=fancy)
    took = f"({int(state.elapsed(now))}s)"
    return [(frame, "accent"), (" " + phase.ljust(text_w) + " " * gap, ""), (full, "accent"), (head + empty, "dim"),
            (f"{pct:>{num_w - 1}}%", "bold"), (took.rjust(el_w), "dim")]
