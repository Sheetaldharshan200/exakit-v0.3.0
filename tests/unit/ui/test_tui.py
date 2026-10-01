"""The Textual screens, headless: the renderer's calls reach the app from a worker thread, the keys and the mouse answer the questions.

Skipped where Textual is not installed; the CI test job installs the pinned version.
"""

from __future__ import annotations

import importlib.util
import io
import unittest
from unittest import mock

from exakit.domain.errors import Failed
from exakit.domain.plan import Plan, Step, StepState
from exakit.domain.result import Result
from exakit.ui.console import ConsoleRenderer
from exakit.ui.widgets import PLAIN, Option

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def _mirror():
    buffer = io.StringIO()
    return ConsoleRenderer(palette=PLAIN, out=buffer, err=buffer, interactive=False), buffer


@unittest.skipUnless(HAVE_TEXTUAL, "textual is not installed here")
class ScreensTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, job, keys=(), size=(120, 40), clicks=()):
        """Run ``job`` inside the app from its worker thread; press ``keys`` (or click) once a question is up; return what the app showed."""
        from exakit.ui.tui.app import KitApp
        from exakit.ui.tui.choices import ChoiceList
        from exakit.ui.tui.panels import LogPane, PlanPanel
        from exakit.ui.tui.renderer import TuiRenderer
        mirror, buffer = _mirror()
        app = KitApp(title="Exasol Personal Local Starter Kit", subtitle="test")
        renderer = TuiRenderer(app, mirror)
        app.job = lambda: job(renderer)
        async with app.run_test(size=size) as pilot:
            for _ in range(100):
                await pilot.pause(0.02)
                if (keys or clicks) and len(app.screen_stack) > 1:
                    break
                if app.done:
                    break
            for offset in clicks:
                await pilot.click(ChoiceList, offset=offset)
                await pilot.pause(0.02)
            for key in keys:
                await pilot.press(key)
                await pilot.pause(0.02)
            for _ in range(200):
                if app.done:
                    break
                await pilot.pause(0.02)
            self.assertTrue(app.done, "the command never finished")
            rows = {key: text.plain for key, text in app.query_one(PlanPanel).texts.items()}
            log = [text.plain for text in app.query_one(LogPane).lines]
            await pilot.press("enter")
        return app, buffer.getvalue(), rows, log

    async def test_lines_steps_and_live_rows_reach_the_app_and_the_transcript(self):
        from exakit.ui.tui.panels import ProgressRow
        seen = {}

        def job(ui):
            ui.banner("Exasol Personal Local Starter Kit", "Platform: macos (arm64)")
            ui.info("hello")
            ui.ok("done")
            plan = Plan("Install", [Step("install", "launcher", StepState.PENDING, label="Step 1/6  Exasol launcher"), Step("install", "runtime", StepState.DONE)])
            ui.plan(plan)
            ui.step_begin(plan.steps[0])
            with ui.progress("Downloading exapump") as report:
                report(50, 100)
                seen["live"] = ui.app.call_from_thread(lambda: len(ui.app.query(ProgressRow)))
            seen["after"] = ui.app.call_from_thread(lambda: len(ui.app.query(ProgressRow)))
            ui.step_end(Step("install", "launcher", StepState.DONE, label="Step 1/6  Exasol launcher"))
            return Result(True, "ok")

        app, transcript, rows, log = await self._run(job)
        self.assertEqual(app.outcome().status, "ok")
        self.assertIn("- hello", transcript)
        self.assertIn("[ok] done", transcript)
        self.assertEqual(seen, {"live": 1, "after": 0})
        self.assertEqual(app.final, "Finished - press Enter to close")
        self.assertEqual(set(rows), {"install/launcher", "install/runtime"})
        self.assertIn("✓ Step 1/6  Exasol launcher", rows["install/launcher"])
        self.assertIn("Step 1/6  Exasol launcher", log)

    async def test_a_working_line_is_a_live_row_that_the_next_line_removes(self):
        from exakit.ui.tui.panels import ProgressRow
        seen = {}

        def job(ui):
            ui.working("Downloading exapump v0.13.0")
            seen["live"] = ui.app.call_from_thread(lambda: len(ui.app.query(ProgressRow)))
            ui.ok("exapump v0.13.0 installed")
            seen["after"] = ui.app.call_from_thread(lambda: len(ui.app.query(ProgressRow)))
            return Result(True, "ok")

        _app, transcript, _rows, log = await self._run(job)
        self.assertEqual(seen, {"live": 1, "after": 0})
        self.assertNotIn("Downloading exapump v0.13.0", log)
        self.assertIn("✓ exapump v0.13.0 installed", log)
        self.assertIn("- Downloading exapump v0.13.0", transcript)          # the plain transcript keeps the record

    async def test_select_answers_with_the_arrow_keys(self):
        answers = []

        def job(ui):
            answers.append(ui.select("Pick one", [Option("a", "A"), Option("b", "B"), Option("c", "C")], default=1))
            return Result(True, "ok")

        _app, transcript, _rows, _log = await self._run(job, keys=("down", "enter"))
        self.assertEqual(answers, ["b"])
        self.assertIn("? Pick one b", transcript)

    async def test_select_takes_a_digit_a_click_and_escape_backs_out(self):
        answers = []

        def job(ui):
            answers.append(ui.select("Pick one", [Option("a", "A"), Option("b", "B"), Option("c", "C")], default=1))
            answers.append(ui.select("Again", [Option("a", "A"), Option("b", "B")], default=1))
            return Result(True, "ok")

        await self._run(job, keys=("3", "escape"))
        self.assertEqual(answers, ["c", None])

    async def test_a_click_chooses_a_row_and_a_click_ticks_a_box(self):
        answers = []

        def job(ui):
            answers.append(ui.select("Click one", [Option("a", "A"), Option("b", "B")], default=1))
            return Result(True, "ok")

        await self._run(job, clicks=((4, 1),))
        self.assertEqual(answers, ["b"])
        answers.clear()

        def job2(ui):
            answers.append(ui.checkboxes("Datasets", [Option("tpch", "TPC-H"), Option("energy", "Energy")], defaults=["tpch"]))
            return Result(True, "ok")

        await self._run(job2, clicks=((4, 1),), keys=("enter",))
        self.assertEqual(answers, [["tpch", "energy"]])

    async def test_checkboxes_tick_with_space_and_continue_with_enter(self):
        answers = []

        def job(ui):
            answers.append(ui.checkboxes("Datasets", [Option("tpch", "TPC-H"), Option("energy", "Energy"), Option("weather", "Weather")], defaults=["tpch"]))
            return Result(True, "ok")

        await self._run(job, keys=("down", "space", "enter"))
        self.assertEqual(answers, [["tpch", "energy"]])

    async def test_an_exclusive_row_clears_the_others_and_is_cleared_by_them(self):
        answers = []

        def job(ui):
            rows = [Option("tpch", "TPC-H"), Option("energy", "Energy"), Option("skip", "Skip", exclusive=True)]
            answers.append(ui.checkboxes("Datasets", rows, defaults=["tpch", "energy"]))
            answers.append(ui.checkboxes("Datasets", rows, defaults=["skip"]))
            return Result(True, "ok")

        await self._run(job, keys=("down", "down", "space", "enter", "space", "enter"))
        self.assertEqual(answers, [["skip"], ["tpch"]])

    async def test_checkboxes_a_and_n_take_all_and_none(self):
        answers = []

        def job(ui):
            answers.append(ui.checkboxes("Datasets", [Option("tpch", "TPC-H"), Option("energy", "Energy")], defaults=[]))
            answers.append(ui.checkboxes("Datasets", [Option("tpch", "TPC-H"), Option("energy", "Energy")], defaults=["tpch"]))
            return Result(True, "ok")

        await self._run(job, keys=("a", "enter", "n", "enter"))
        self.assertEqual(answers, [["tpch", "energy"], []])

    async def test_confirm_and_prompt(self):
        answers = []

        def job(ui):
            answers.append(ui.confirm("Install the kit?", default=True))
            answers.append(ui.confirm("Really?", default=True))
            answers.append(ui.prompt("Schema", default="STARTER_KIT"))
            return Result(True, "ok")

        await self._run(job, keys=("enter", "n", "enter"))
        self.assertEqual(answers, [True, False, "STARTER_KIT"])

    async def test_a_failure_in_the_command_is_carried_out_of_the_app(self):
        def job(ui):
            ui.error("Setup failed")
            raise Failed("the step did not finish", remedy="exakit install")

        app, transcript, _rows, _log = await self._run(job)
        self.assertIn("[x] Setup failed", transcript)
        self.assertTrue(app.final.startswith("Stopped"))
        with self.assertRaises(Failed) as caught:
            app.outcome()
        self.assertEqual(caught.exception.remedy, "exakit install")

    async def test_the_app_keeps_the_terminals_colours(self):
        from exakit.ui.tui.app import KitApp
        app = KitApp(title="t")
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.02)
            self.assertTrue(app.ansi_color)
            self.assertEqual(app.screen.styles.background.a, 0, "the screen paints no background of its own")


class WantedTest(unittest.TestCase):
    def test_only_interactive_flows_in_a_utf8_terminal_want_the_screens(self):
        from exakit.ui import tui

        class Tty(io.StringIO):
            def isatty(self):
                return True

        env = {"LANG": "en_US.UTF-8", "TERM": "xterm-256color"}
        with mock.patch("exakit.ui.tui.has_terminal", lambda out: True):
            self.assertTrue(tui.wanted(env, Tty(), command="install", args=[], json=False, dry_run=False))
            self.assertTrue(tui.wanted(env, Tty(), command="persona", args=["apply", "analyst"], json=False, dry_run=False))
            self.assertFalse(tui.wanted(env, Tty(), command="persona", args=[], json=False, dry_run=False))
            self.assertFalse(tui.wanted(env, Tty(), command="status", args=[], json=False, dry_run=False))
            self.assertFalse(tui.wanted(env, Tty(), command="ui", args=[], json=False, dry_run=False), "ui draws its own app")
            self.assertTrue(tui.terminal_ok(env, Tty(), json=False, dry_run=False))
            self.assertFalse(tui.terminal_ok(env, Tty(), json=True, dry_run=False))
            self.assertFalse(tui.wanted(env, Tty(), command="install", args=[], json=True, dry_run=False))
            self.assertFalse(tui.wanted(env, Tty(), command="install", args=[], json=False, dry_run=True))
            self.assertFalse(tui.wanted({**env, "EXAKIT_TUI": "0"}, Tty(), command="install", args=[], json=False, dry_run=False))
            self.assertFalse(tui.wanted({**env, "EXAKIT_DRY_RUN": "1"}, Tty(), command="install", args=[], json=False, dry_run=False))
            self.assertFalse(tui.wanted({"LANG": "C"}, Tty(), command="install", args=[], json=False, dry_run=False))
        self.assertFalse(tui.wanted(env, io.StringIO(), command="install", args=[], json=False, dry_run=False))

    def test_load_fails_softly_on_a_folder_without_the_toolkit(self):
        import tempfile
        from pathlib import Path
        from exakit.ui import tui
        if HAVE_TEXTUAL:
            self.skipTest("textual is importable here, so load() cannot fail")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(tui.load(Path(tmp)))
