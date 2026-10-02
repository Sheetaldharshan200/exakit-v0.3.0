"""The host clipboard tool the screens hand a selection to."""

from __future__ import annotations

import unittest
from unittest import mock

from exakit.adapters import clipboard


class ClipboardTest(unittest.TestCase):
    def test_the_tool_is_the_first_one_installed_for_the_os(self):
        self.assertEqual(clipboard.command_for("Darwin", which=lambda n: "/usr/bin/pbcopy"), ["pbcopy"])
        self.assertEqual(clipboard.command_for("Windows", which=lambda n: "C:/clip"), ["clip"])
        self.assertEqual(clipboard.command_for("Linux", which=lambda n: "/usr/bin/xclip" if n == "xclip" else None), ["xclip", "-selection", "clipboard"])
        self.assertIsNone(clipboard.command_for("Linux", which=lambda n: None))
        self.assertIsNone(clipboard.command_for("Plan9", which=lambda n: "/bin/x"))

    def test_copy_without_a_tool_says_so_instead_of_failing(self):
        import platform
        with mock.patch.object(platform, "system", lambda: "Plan9"):
            self.assertFalse(clipboard.copy("hello"))
