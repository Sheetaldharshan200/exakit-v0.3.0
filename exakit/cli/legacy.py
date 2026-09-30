"""Passthrough to the legacy shell CLI for commands Python has not taken over yet (phases A to C).

The migrated set is ``cli.MIGRATED_COMMANDS``; everything else runs
``setup/legacy-exakit`` (bash) or ``setup/legacy-exakit.ps1`` (Windows) with
the terminal attached and the exit code passed straight through. ``install``
gets one extra: ``EXAKIT_PERSONA`` is expanded into the answers the legacy
installer understands before the hand-over.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from exakit.app import Context
from exakit.app.machine import kit_root
from exakit.app.persona import install_env
from exakit.domain.errors import BadInput, NotInstalled

LEGACY_SH = "setup/legacy-exakit"
LEGACY_PS1 = "setup/legacy-exakit.ps1"
LEGACY_INSTALLERS = {"macos": "setup/setup-macos.sh", "linux": "setup/setup-linux.sh", "windows": "setup/setup-windows.ps1"}


def _command(root: Path, script: str, args: list[str]) -> list[str]:
    if script.endswith(".ps1"):
        shell = "powershell" if os.name == "nt" else "pwsh"
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / script), *args]
    return ["bash", str(root / script), *args]


def run(ctx: Context, command: str, args: list[str]) -> int:
    """Run a legacy command in the foreground and return its exit code."""
    root = kit_root(ctx)
    script = LEGACY_PS1 if ctx.platform.os == "windows" else LEGACY_SH
    if not (root / script).is_file():
        raise NotInstalled(f"This kit copy has no legacy command file for '{command}'.", remedy="exakit update",
                           hint=f"expected {root / script}")
    env = dict(os.environ)
    argv = [command, *args]
    if command == "install":
        script = LEGACY_INSTALLERS[ctx.platform.os]
        argv = []
        persona = env.get("EXAKIT_PERSONA")
        if persona:
            if persona not in ctx.catalog.persona_ids():
                raise BadInput(f"Unknown persona '{persona}' (EXAKIT_PERSONA). Known personas: {' '.join(ctx.catalog.persona_ids())}.")
            env.update(install_env(ctx, persona))
            ctx.log.line("INFO", f"persona {persona}: {install_env(ctx, persona)}")
    sys.stdout.flush()
    return subprocess.call(_command(root, script, argv), env=env)
