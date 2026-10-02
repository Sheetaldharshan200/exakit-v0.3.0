"""Plain progress prints the quarter it reached, once."""

from __future__ import annotations

import io
import unittest

from exakit.ui.console import ConsoleRenderer
from exakit.ui.widgets import PLAIN


class MilestoneTest(unittest.TestCase):
    def test_a_download_that_lands_in_one_chunk_says_100_percent_once(self):
        out = io.StringIO()
        ui = ConsoleRenderer(palette=PLAIN, out=out, err=out, interactive=False)
        with ui.progress("Downloading wheel") as bar:
            bar.update(116_000, 116_000)
        lines = [line for line in out.getvalue().splitlines() if "Downloading wheel:" in line]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("100%", lines[0])

    def test_a_steady_download_still_reports_each_quarter(self):
        out = io.StringIO()
        ui = ConsoleRenderer(palette=PLAIN, out=out, err=out, interactive=False)
        with ui.progress("Downloading engine") as bar:
            for done in range(0, 4_000_001, 250_000):
                bar.update(done, 4_000_000)
        marks = [line.split(":")[1].split("%")[0].strip() for line in out.getvalue().splitlines() if "Downloading engine:" in line]
        self.assertEqual(marks, ["25", "50", "75", "100"])
