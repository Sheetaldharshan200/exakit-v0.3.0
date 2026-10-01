"""A child process never inherits the kit's folder on PYTHONPATH (D43): the kit's own mcp package would shadow the MCP SDK."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from exakit.adapters.clients import handshake
from exakit.adapters.process.runner import KIT_ROOT, clean_env


class CleanEnvTest(unittest.TestCase):
    def test_the_kit_folder_leaves_pythonpath_and_other_entries_stay(self):
        env = clean_env({"PYTHONPATH": os.pathsep.join([str(KIT_ROOT), "/opt/mine"]), "HOME": "/h"})
        self.assertEqual(env["PYTHONPATH"], "/opt/mine")
        self.assertEqual(env["HOME"], "/h")
        self.assertNotIn("PYTHONPATH", clean_env({"PYTHONPATH": str(KIT_ROOT)}))
        self.assertEqual(clean_env({"A": "1"}), {"A": "1"})

    def test_the_handshake_hands_the_server_a_clean_environment(self):
        seen = {}

        class Proc:
            def communicate(self, text, timeout=None):
                return "", ""

            def kill(self):
                return None

        def popen(cmd, **kwargs):
            seen["env"] = kwargs["env"]
            return Proc()

        with mock.patch.object(handshake.subprocess, "Popen", popen):
            handshake.stdio_handshake("uvx", "exasol-mcp-server@2.2.0", {"PYTHONPATH": str(KIT_ROOT), "EXA_DSN": "x"})
        self.assertNotIn("PYTHONPATH", seen["env"])
        self.assertEqual(seen["env"]["EXA_DSN"], "x")
