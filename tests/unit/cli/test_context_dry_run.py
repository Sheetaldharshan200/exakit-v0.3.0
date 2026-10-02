"""A dry run writes no log under the kit home: it promises to change nothing there."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from exakit.adapters.fs.log import NullLog
from exakit.cli import _context


class DryRunLogTest(unittest.TestCase):
    def test_a_dry_run_gets_no_file_log_and_a_real_run_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOME": tmp, "EXAKIT_HOME": f"{tmp}/home", "EXAKIT_BIN_DIR": f"{tmp}/bin"}
            Path(env["EXAKIT_HOME"]).mkdir()
            with mock.patch.dict(os.environ, env, clear=False):
                dry = _context.build(json=False, yes=False, dry_run=True, readonly=False, mutating=True)
                self.assertIsInstance(dry.log, NullLog)
                real = _context.build(json=False, yes=False, dry_run=False, readonly=False, mutating=True)
                self.assertNotIsInstance(real.log, NullLog)
