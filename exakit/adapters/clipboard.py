"""The clipboard through the terminal's host - pbcopy, clip, wl-copy, xclip or xsel - because OSC 52 never reaches Terminal.app or iTerm2 by default."""

from __future__ import annotations

import platform
import shutil
import subprocess
from collections.abc import Callable

TOOLS: dict[str, tuple[list[str], ...]] = {
    "darwin": (["pbcopy"],),
    "windows": (["clip"],),
    "linux": (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]),
}


def command_for(system: str, which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    """The host's clipboard command for this OS, or None where none is installed."""
    for cmd in TOOLS.get(system.lower(), ()):
        if which(cmd[0]):
            return cmd
    return None


def copy(text: str) -> bool:
    """Put ``text`` on the host clipboard; False when no tool is there or it failed."""
    cmd = command_for(platform.system())
    if not cmd:
        return False
    try:
        subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return True
