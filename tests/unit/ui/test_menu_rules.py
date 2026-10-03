"""The shared tick rule with heading rows: a heading is never ticked and never blocks "Everything"."""

from __future__ import annotations

import unittest

from exakit.ui.menu_rules import tick
from exakit.ui.widgets import Option

ROWS = [Option("everything", "EVERYTHING", everything=True), Option("h", "Add-ons", heading=True),
        Option("a", "dash-server"), Option("b", "json-tables"), Option("skip", "Skip", exclusive=True)]


class HeadingTickTest(unittest.TestCase):
    def test_everything_ticks_the_rows_and_never_a_heading(self):
        chosen: set[str] = set()
        tick(ROWS, chosen, 0)
        self.assertEqual(chosen, {"everything", "a", "b"})

    def test_ticking_every_row_ticks_everything_with_a_heading_in_the_list(self):
        chosen: set[str] = set()
        tick(ROWS, chosen, 2)
        tick(ROWS, chosen, 3)
        self.assertEqual(chosen, {"a", "b", "everything"})

    def test_a_heading_cannot_be_ticked(self):
        chosen: set[str] = {"a"}
        tick(ROWS, chosen, 1)
        self.assertEqual(chosen, {"a"})
