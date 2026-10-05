"""When a desktop app the kit configures was started: an app that reads its config only at launch has not seen a
change made after that moment."""

from __future__ import annotations

import time
from datetime import datetime

from .runner import Runner

# How each app's main process is found: the macOS executable path ``ps`` prints, the Windows process name.
APPS: dict[str, dict[str, str]] = {"claude_desktop": {"macos": "/Claude.app/Contents/MacOS/Claude", "windows": "Claude"}}


def started_at(runner: Runner, os_name: str, app: str) -> float | None:
    """The epoch second the app's earliest running process started; None when it is not running or this OS cannot say."""
    names = APPS.get(app) or {}
    if os_name == "macos" and names.get("macos"):
        return _macos(runner, names["macos"])
    if os_name == "windows" and names.get("windows"):
        return _windows(runner, names["windows"])
    return None


def _macos(runner: Runner, executable: str) -> float | None:
    done = runner.run(["ps", "-axo", "lstart=,comm="], timeout=10)
    found = []
    for line in done.out.splitlines() if done.ok else []:
        parts = line.split()                          # "Mon Oct  5 11:39:30 2026 /Applications/Claude.app/..."
        if len(parts) < 6 or not " ".join(parts[5:]).endswith(executable):
            continue
        stamp = " ".join(parts[:5])
        try:
            found.append(time.mktime(time.strptime(stamp, "%a %b %d %H:%M:%S %Y")))
        except ValueError:
            continue
    return min(found) if found else None


def _windows(runner: Runner, name: str) -> float | None:
    script = (f"$p = Get-Process -Name '{name}' -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object -First 1; "
              "if ($p) { $p.StartTime.ToUniversalTime().ToString('o') }")
    done = runner.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=20)
    text = done.out.strip().splitlines()[0].strip() if done.ok and done.out.strip() else ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() if text else None
    except ValueError:
        return None
