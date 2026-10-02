"""The live line of the console renderer: a spinner with a detail and the time so far, or the progress line of the job on top."""

from __future__ import annotations

import threading
import time
from typing import IO

from .progress import ProgressState, elapsed_text, progress_parts
from .widgets import Palette, term_cols

SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Milestones:
    """Plain-mode progress: one line at each quarter of a byte or item count, one line per phase of a staged job."""

    def __init__(self, console, state: ProgressState) -> None:
        self.console = console
        self.state = state
        self.quarter = 0
        self.phase = ""
        state.on_change = self.changed

    def changed(self, state: ProgressState) -> None:
        """Print what crossed a quarter or named a new phase, once."""
        p = self.console.p
        if state.unit == "percent":
            if state.phase and state.phase != self.phase:
                self.phase = state.phase
                self.console._w(f"    {p.dim}{p.bullet}{p.reset} {state.phase}")
            return
        if not state.total:
            return
        quarter = min(4, state.done * 4 // state.total)
        if quarter > self.quarter:                  # one line for the quarter reached: a fast chunk that crosses three says 100% once
            self.quarter = quarter
            self.console._w(f"      {p.dim}{state.label}: {quarter * 25}%  {state.text().split(' · ')[-1]}{p.reset}")


class Spinner:
    """Redraws one line on a thread until stopped: a spinner with a label, or the progress line of the job on top of the stack."""

    def __init__(self, out: IO[str], template: str, palette: Palette) -> None:
        self.out = out
        self.template = template
        self.p = palette
        self.detail = ""
        self.states: list[ProgressState] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._t0 = time.monotonic()
        self._cols = term_cols()

    def start(self) -> None:
        """Start the spinner."""
        self.out.write("\x1b[?25l")
        self._thread.start()

    def _line(self, frame: str) -> str:
        if self.states:
            styles = {"accent": self.p.accent, "dim": self.p.dim, "bold": self.p.bold, "": ""}
            parts = progress_parts(self.states[-1], frame=frame, cols=self._cols, fancy=self.p.fancy)
            return "    " + "".join(f"{styles[style]}{text}{self.p.reset}" if style else text for text, style in parts)
        return "  " + self.template.format(frame=frame, detail=self.detail, elapsed=elapsed_text(time.monotonic() - self._t0)).rstrip()

    def _run(self) -> None:
        i = 0
        while not self._stop.is_set():
            self.out.write("\r\x1b[K" + self._line(SPIN_FRAMES[i % len(SPIN_FRAMES)]))
            self.out.flush()
            i += 1
            self._stop.wait(0.1)

    def stop(self) -> None:
        """Stop the spinner and clear its line."""
        self._stop.set()
        self._thread.join(timeout=1)
        self.out.write("\r\x1b[K\x1b[?25h")
        self.out.flush()
