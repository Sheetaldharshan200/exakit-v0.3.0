"""A long command's lines arrive as they are printed, and the launcher's lines move the deploy bar (D38)."""

from __future__ import annotations

import sys
import unittest

from exakit.adapters.process.runner import Completed, SubprocessRunner
from exakit.app import deploy
from exakit.domain.catalog import validate_component
from exakit.ui.progress import ProgressState
from tests.unit.app.harness import MANIFEST, Sandbox
from tests.unit.fakes import FakeRunner


class StreamTest(unittest.TestCase):
    def test_the_real_runner_hands_every_line_over_and_answers_with_them(self):
        seen = []
        done = SubprocessRunner().stream([sys.executable, "-c", "import sys; print('one'); print('two', file=sys.stderr); print('three')"], seen.append, timeout=30)
        self.assertEqual(done.code, 0)
        self.assertEqual(set(seen), {"one", "two", "three"})
        self.assertEqual(set(done.out.splitlines()), {"one", "two", "three"})

    def test_a_missing_command_is_code_127(self):
        self.assertEqual(SubprocessRunner().stream(["/no/such/launcher", "install"], lambda line: None).code, 127)

    def test_the_fake_streams_its_scripted_answer(self):
        runner = FakeRunner({("exasol", "install", "local"): Completed(0, "validating presets\nCompleted deploying\n", "")})
        seen = []
        runner.stream(["exasol", "install", "local"], seen.append)
        self.assertEqual(seen, ["validating presets", "Completed deploying"])


class MilestoneTest(unittest.TestCase):
    def test_the_launchers_lines_become_stages_from_the_catalog_table(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            bar = ProgressState("Deploying the local database", unit="percent")
            on_line = deploy._milestone_reader(box.ctx, bar)
            on_line("2026-10-01 validating presets ...")
            self.assertEqual((bar.pct, bar.ceiling, bar.phase), (5, 10, "Preparing to deploy"))
            on_line("found resource in cache: exasol-db")
            self.assertEqual((bar.pct, bar.ceiling, bar.seconds, bar.phase), (35, 65, 25.0, "Getting Exasol ready"))
            on_line("something unrelated")
            self.assertEqual(bar.pct, 35)
            on_line("extracting preset files")                 # an earlier milestone arriving late never rewinds
            self.assertEqual(bar.pct, 35)
            on_line("Completed deploying the local database")
            self.assertEqual((bar.pct, bar.phase), (100, "Deployed"))
        finally:
            box.close()

    def test_the_eula_notice_is_shown_as_it_passes(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            deploy._milestone_reader(box.ctx, ProgressState("x", unit="percent"))("  By continuing you accept the End User License Agreement")
            self.assertIn("End User License Agreement", box.out.getvalue())
        finally:
            box.close()

    def test_the_catalog_validates_the_milestone_table(self):
        doc = {"schema_version": 1, "id": "personal", "title": "P", "kind": "runtime", "deploy_milestones": [{"match": "x", "pct": 50, "ceiling": 40, "seconds": 1, "phase": "P"}]}
        self.assertTrue(any("above its ceiling" in p for p in validate_component(doc, expected_id="personal")))
        doc["deploy_milestones"] = [{"match": "x", "pct": 5, "ceiling": 10, "seconds": 2, "phase": "P"}]
        self.assertEqual([p for p in validate_component(doc, expected_id="personal") if "milestone" in p], [])
        shipped = Sandbox(manifest=MANIFEST)
        try:
            self.assertGreaterEqual(len(shipped.ctx.catalog.component("personal").deploy_milestones), 8)
        finally:
            shipped.close()
