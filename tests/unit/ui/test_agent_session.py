"""An AI agent's session: plain output, no question, no screens - even on a pseudo-terminal."""

from __future__ import annotations

import io
import unittest

from exakit.domain.settings import agent_session
from exakit.ui import make_renderer
from exakit.ui.widgets import PLAIN

MARKERS = ("CLAUDECODE", "GEMINI_CLI", "CODEX_SANDBOX")


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


class AgentSessionTest(unittest.TestCase):
    def test_a_marker_or_the_switch_makes_an_agent_session_and_zero_is_a_human(self):
        self.assertFalse(agent_session({}, MARKERS))
        self.assertTrue(agent_session({"CLAUDECODE": "1"}, MARKERS))
        self.assertTrue(agent_session({"CODEX_SANDBOX": "seatbelt"}, MARKERS))
        self.assertTrue(agent_session({"EXAKIT_AGENT": "1"}, ()))
        self.assertFalse(agent_session({"CLAUDECODE": "1", "EXAKIT_AGENT": "0"}, MARKERS))
        self.assertFalse(agent_session({"CLAUDECODE": ""}, MARKERS))

    def test_an_agent_on_a_pseudo_terminal_gets_plain_output_and_no_question(self):
        env = {"LANG": "en_US.UTF-8", "TERM": "xterm-256color"}
        human = make_renderer(json=False, env=env, out=FakeTty())
        agent = make_renderer(json=False, env={**env, "EXAKIT_AGENT": "1"}, out=FakeTty())
        self.assertIsNot(human.p, PLAIN)
        self.assertIs(agent.p, PLAIN)
        self.assertFalse(agent.interactive)

    def test_the_screens_never_draw_for_an_agent(self):
        from exakit.ui import tui
        env = {"LANG": "en_US.UTF-8", "EXAKIT_AGENT": "1"}
        self.assertFalse(tui.terminal_ok(env, FakeTty(), json=False, dry_run=False))

    def test_the_kit_settings_carry_the_markers(self):
        from pathlib import Path
        from exakit.domain.catalog import Catalog
        catalog = Catalog.load(Path(__file__).resolve().parents[3], Path("/nonexistent"), warn=lambda m: None)
        self.assertEqual(catalog.kit.agent_markers, MARKERS)
