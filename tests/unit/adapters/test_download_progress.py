"""Downloads report their bytes as they land, and the renderers draw that honestly - the one progress line of D38."""

from __future__ import annotations

import io
import unittest

from exakit.adapters.net.http import _copy
from exakit.domain.plan import Step, StepState
from exakit.ui.console import ConsoleRenderer
from exakit.ui.progress import ProgressState, bar_cells, creep, elapsed_text, human_size, layout, progress_parts
from exakit.ui.silent import SilentRenderer
from exakit.ui.widgets import FANCY, PLAIN


class _Response:
    def __init__(self, body: bytes, length: str | None) -> None:
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Length": length} if length is not None else {}

    def read(self, n: int) -> bytes:
        return self._buf.read(n)


class CopyTest(unittest.TestCase):
    def test_every_chunk_and_the_final_size_reach_the_callback(self):
        seen = []
        out = io.BytesIO()
        _copy(_Response(b"x" * (600 * 1024), str(600 * 1024)), out, lambda done, total: seen.append((done, total)))
        self.assertEqual(out.getvalue(), b"x" * (600 * 1024))
        self.assertEqual(seen[-1], (600 * 1024, 600 * 1024))
        self.assertGreaterEqual(len(seen), 3)

    def test_without_a_content_length_the_total_is_unknown_until_the_end(self):
        seen = []
        _copy(_Response(b"abc", None), io.BytesIO(), lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(3, None), (3, 3)])


class ProgressStateTest(unittest.TestCase):
    def test_bytes_and_items_turn_into_a_percent_and_a_count_in_the_phase(self):
        state = ProgressState("Downloading exapump")
        state(150 * 1024 * 1024, 180 * 1024 * 1024)
        self.assertEqual(state.pct, 83)
        self.assertEqual(state.text(), "Downloading exapump · 150.0 MB/180.0 MB")
        files = ProgressState("Loading 3 files", unit="items")
        files.set_phase("orders.csv")
        files.update(1, 3)
        self.assertEqual((files.pct, files.text()), (33, "orders.csv · 1/3"))

    def test_the_creep_fills_a_stage_but_never_reaches_the_next_milestone(self):
        self.assertEqual(creep(35, 65, 25, 0), 35)
        self.assertEqual(creep(35, 65, 25, 12.5), 50)
        self.assertEqual(creep(35, 65, 25, 1000), 64)
        self.assertEqual(creep(35, 65, 0, 100), 35)
        state = ProgressState("Deploying", unit="percent")
        state.stage(35, 65, 25, "Getting Exasol ready")
        self.assertEqual(state.position(state.segment_t0), 35)
        self.assertEqual(state.position(state.segment_t0 + 10), 47)
        state.stage(20, 35, 5, "an earlier milestone, late")       # never walks backwards
        self.assertGreaterEqual(state.position(state.segment_t0), 47)
        state.stage(100, 100, 0, "Deployed")
        self.assertEqual(state.position(), 100)

    def test_the_layout_and_the_bar_cells(self):
        text, gap, bar, num, el = layout(100)
        self.assertEqual((text + gap + bar + num + el), 91)
        self.assertEqual(layout(20), layout(30))                    # floors hold on a narrow terminal
        self.assertEqual(bar_cells(50, 10, fancy=False), ("#####", "", "....."))
        self.assertEqual(bar_cells(47, 10, fancy=True), ("████", "▋", "░░░░░"))
        self.assertEqual(bar_cells(100, 4, fancy=True), ("████", "", ""))
        self.assertEqual(human_size(13001728), "12.4 MB")
        self.assertEqual(elapsed_text(65), "1m 05s")

    def test_the_line_has_the_phase_the_bar_the_percent_and_the_elapsed(self):
        state = ProgressState("Deploying", unit="percent")
        state.stage(35, 65, 25, "Getting Exasol ready")
        line = "".join(t for t, _ in progress_parts(state, frame="⠋", cols=100, fancy=True, now=state.segment_t0 + 10))
        self.assertTrue(line.startswith("⠋ Getting Exasol ready"))
        self.assertIn("█", line)
        self.assertIn(" 47%", line)
        self.assertTrue(line.rstrip().endswith("(10s)"))


class RendererProgressTest(unittest.TestCase):
    def test_plain_mode_prints_a_line_at_each_quarter_only(self):
        out = io.StringIO()
        r = ConsoleRenderer(palette=PLAIN, out=out, interactive=False)
        with r.progress("Downloading exapump") as report:
            for done in (10, 20, 30, 50, 60, 80, 100):
                report(done * 1024, 100 * 1024)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 4)
        self.assertIn("Downloading exapump: 25%", lines[0])
        self.assertIn("100%  100 KB/100 KB", lines[-1])

    def test_plain_mode_prints_one_line_per_phase_of_a_staged_job(self):
        out = io.StringIO()
        r = ConsoleRenderer(palette=PLAIN, out=out, interactive=False)
        with r.progress("Deploying", unit="percent") as bar:
            bar.stage(5, 10, 2, "Preparing to deploy")
            bar.stage(10, 20, 2, "Preparing to deploy")
            bar.stage(35, 65, 25, "Getting Exasol ready")
        self.assertEqual([line.strip() for line in out.getvalue().splitlines() if line.strip()], ["- Preparing to deploy", "- Getting Exasol ready"])

    def test_fancy_mode_draws_the_job_on_top_of_the_stack(self):
        out = io.StringIO()
        r = ConsoleRenderer(palette=FANCY, out=out, interactive=True)
        with r.progress("Installing json-tables", unit="percent") as outer:
            outer.stage(0, 65, 40, "json-tables · installing")
            self.assertEqual(r._spin.states, [outer])
            with r.progress("Downloading the wheel") as inner:
                inner(50, 100)
                self.assertEqual(r._spin.states[-1], inner)
                self.assertIn("Downloading the whe", r._spin._line("⠋"))     # the phase cell of an 80-column line
            self.assertEqual(r._spin.states, [outer])
        self.assertIsNone(r._spin)
        self.assertIn("\x1b[?25h", out.getvalue())

    def test_a_line_written_under_a_spinner_clears_the_spinner_line_first(self):
        out = io.StringIO()
        r = ConsoleRenderer(palette=FANCY, out=out, interactive=True)
        with r.busy("Deploying"):
            r.info("the launcher said hello")
        text = out.getvalue()
        self.assertIn("the launcher said hello\n", text)
        self.assertIn("\r\x1b[K    ", text[:text.index("the launcher said hello")][-40:])

    def test_an_install_step_is_a_heading_and_closes_with_a_tick_and_its_time(self):
        out = io.StringIO()
        r = ConsoleRenderer(palette=PLAIN, out=out, interactive=False)
        step = Step("install", "launcher", StepState.PENDING, label="Step 1/6  Exasol launcher")
        r.step_begin(step)
        r.step_end(Step("install", "launcher", StepState.DONE, label="Step 1/6  Exasol launcher"))
        r.step_end(Step("install", "runtime", StepState.DONE, label="Step 2/6  Local database deployment"), detail="already done, skipping")
        lines = [line.rstrip() for line in out.getvalue().splitlines() if line.strip()]
        self.assertTrue(lines[0].endswith("Step 1/6  Exasol launcher") and "[ok]" not in lines[0])
        self.assertEqual(lines[1], "  [ok] Step 1/6  Exasol launcher")
        self.assertEqual(lines[2], "  [ok] Step 2/6  Local database deployment already done, skipping")

    def test_a_working_line_is_replaced_by_the_outcome_in_fancy_mode_and_printed_in_plain_mode(self):
        out = io.StringIO()
        r = ConsoleRenderer(palette=FANCY, out=out, interactive=True)
        r.working("Downloading exapump v0.13.0")
        self.assertIsNotNone(r._spin)
        self.assertTrue(r._transient)
        r.ok("exapump v0.13.0 installed")
        self.assertIsNone(r._spin)
        text = out.getvalue()
        self.assertIn("exapump v0.13.0 installed\n", text)
        self.assertNotIn("Downloading exapump v0.13.0\n", text)              # never a permanent line
        plain = io.StringIO()
        ConsoleRenderer(palette=PLAIN, out=plain, interactive=False).working("Downloading exapump v0.13.0")
        self.assertEqual(plain.getvalue().strip(), "- Downloading exapump v0.13.0")

    def test_the_silent_renderer_logs_the_label_and_draws_nothing(self):
        from tests.unit.fakes import ListLog
        log = ListLog()
        with SilentRenderer(log).progress("Downloading exapump") as report:
            report(1, 2)
        self.assertTrue(any("Downloading exapump" in str(line) for line in log.lines))
