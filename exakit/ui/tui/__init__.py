"""The Textual screens: whether a run wants them, loading the toolkit from its venv, running a command inside the app.

Textual is a third-party package that lives in a venv under the kit home (``adapters/tui_env``),
so nothing here imports it at module level: ``load()`` puts that venv on ``sys.path`` and
imports it, and only then are ``app``, ``panels``, ``screens`` and ``renderer`` imported.
"""

from __future__ import annotations

import importlib
import io
import site
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO

from exakit.domain.result import Result
from exakit.ui import has_terminal, wants_fancy
from exakit.ui.console import ConsoleRenderer
from exakit.ui.widgets import PLAIN

TUI_COMMANDS = frozenset({"install", "marketplace", "update", "uninstall", "mcp-setup", "data-load", "migrate",
                          "repair-runtime", "skills-install", "persona"})


def terminal_ok(env: Mapping[str, str], out: IO[str], *, json: bool, dry_run: bool) -> bool:
    """True when the screens may draw here: a UTF-8 terminal, not --json, not a dry run, EXAKIT_TUI not 0."""
    if json or dry_run or env.get("EXAKIT_DRY_RUN") == "1" or env.get("EXAKIT_TUI") == "0":
        return False
    return has_terminal(out) and wants_fancy(env, out)


def wanted(env: Mapping[str, str], out: IO[str], *, command: str, args: list[str], json: bool, dry_run: bool) -> bool:
    """True when this run draws the screens around the command: an interactive flow (``ui`` draws its own app) on a terminal that allows it."""
    if command not in TUI_COMMANDS or (command == "persona" and "apply" not in args):
        return False
    return terminal_ok(env, out, json=json, dry_run=dry_run)


def load(site_dir: Path) -> bool:
    """Put the screens' venv on sys.path and import the toolkit; False (and the console stays) when that does not work."""
    try:
        site.addsitedir(str(site_dir))
        importlib.import_module("textual")
        importlib.import_module("rich")
    except Exception:
        return False
    return True


def run_dashboard(ctx, data, *, title: str, copier: Callable[[str], bool] | None = None) -> None:
    """Open the dashboard over ``data`` (a ``DashboardData``); actions run the ordinary commands with the screens as ``ctx.ui``."""
    from .dashboard import DashboardApp
    from .renderer import TuiRenderer
    console = ctx.ui
    app = DashboardApp(data, title=title, copier=copier)
    mirror = ConsoleRenderer(palette=PLAIN, out=io.StringIO(), interactive=False, log=ctx.log)
    ctx.ui = TuiRenderer(app, mirror)
    try:
        app.run()
    finally:
        ctx.ui = console


def run(ctx, job: Callable[[], Result], *, title: str, subtitle: str = "", out: IO[str] | None = None,
        copier: Callable[[str], bool] | None = None) -> Result:
    """Run ``job`` inside the app with ``ctx.ui`` as the screens; print the plain transcript when the app closes.

    The job's Result is returned; an ExakitError it raised is raised here, after the console is back.
    """
    from .app import KitApp
    from .renderer import TuiRenderer
    console = ctx.ui
    buffer = io.StringIO()
    mirror = ConsoleRenderer(palette=PLAIN, out=buffer, err=buffer, interactive=False, log=ctx.log, home=getattr(console, "home", ""))
    app = KitApp(title=title, subtitle=subtitle, copier=copier)
    ctx.ui = TuiRenderer(app, mirror)
    app.job = job
    try:
        app.run()
    finally:
        ctx.ui = console
        (out or sys.stdout).write(buffer.getvalue())
        (out or sys.stdout).flush()
    return app.outcome()
