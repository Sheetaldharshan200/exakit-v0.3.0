"""The surfaces that name exakit commands agree with the CLI (tools/command_sync.py)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import command_sync


class CommandSyncTest(unittest.TestCase):
    def test_every_surface_agrees(self):
        self.assertEqual(command_sync.findings(), [])

    def test_a_markdown_code_span_or_block_naming_a_missing_command_is_caught_and_prose_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "x.md"
            page.write_text("Run `exakit mcp-repair` now.\nThe exakit process holds it.\n```bash\nEXAKIT_X=1 exakit frobnicate\n```\n")
            words = [w for _, w in command_sync._markdown_words(page)]
        self.assertEqual(words, ["mcp-repair", "frobnicate"])

    def test_a_code_string_naming_a_missing_command_is_caught_and_comments_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "x.py"
            src.write_text('# exakit nonsense in a comment\nREMEDY = "Run: exakit mcp-repair"\n')
            words = [w for _, w in command_sync._code_words(src)]
        self.assertEqual(words, ["mcp-repair"])

    def test_catalog_rows_carry_the_effect_for_agents(self):
        from exakit.app.kit import help as help_app
        docs = help_app.load_docs(command_sync.REPO / "help")
        rows = {r["command"]: r for r in help_app.json_payload(docs, "all")["commands"] if r["tool"] == "exakit"}
        self.assertEqual((rows["status"]["effect"], rows["status"]["prompt_free"]), ("read", True))
        self.assertEqual((rows["uninstall"]["effect"], rows["uninstall"]["prompt_free"]), ("destructive", False))
        self.assertEqual(rows["persona"]["read_forms"], ["list", "show <id>", "plan <id>"])
        self.assertTrue(rows["ui"]["interactive_only"])
