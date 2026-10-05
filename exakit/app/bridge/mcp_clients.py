"""The AI clients as a person sees them: their names (Claude is the desktop app and Claude Code together), the rows of
the setup menu, and which open app must be reopened before it loads the kit's server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from exakit.adapters.clients import CLIENT_IDS
from exakit.adapters.process.apps import started_at as app_started_at
from exakit.domain.ids import client_rows
from exakit.ui.widgets import Option

from .. import Context

LABELS = {"claude": "Claude", "claude_desktop": "Claude desktop app", "claude_code": "Claude Code", "cursor": "Cursor", "codex": "Codex",
          "vscode_copilot": "GitHub Copilot", "gemini_cli": "Gemini CLI", "opencode": "OpenCode", "continue": "Continue"}
MEMBER_WORDS = {"claude_desktop": "desktop app", "claude_code": "Claude Code"}      # how a group's row names its members


def client_names(ids: list[str]) -> list[str]:
    """Names for client ids in the kit's order; a whole group is named once ("Claude (desktop app and Claude Code)")."""
    names: list[str] = []
    for row, members in client_rows():
        present = [m for m in members if m in ids]
        if not present:
            continue
        if len(members) > 1 and len(present) == len(members):
            names.append(f"{LABELS[row]} ({' and '.join(MEMBER_WORDS.get(m, m) for m in members)})")
        else:
            names += [LABELS.get(m, m) for m in present]
    return names + [c for c in ids if c not in CLIENT_IDS]


def _group_row(row: str, members: tuple[str, ...], states: dict[str, str]) -> Option:
    """One menu row for a group: ticked when any member waits to be connected; the hint says which ones it covers."""
    pending = [m for m in members if states.get(m) == "pending"]
    words = [MEMBER_WORDS.get(m, m) for m in members]
    if not pending:
        hint = "already connected" if any(states.get(m) == "connected" for m in members) else "not installed"
        return Option(row, LABELS[row], hint=hint, disabled=True)
    if len(pending) == len(members):
        return Option(row, LABELS[row], hint=" and ".join(words))
    others = [m for m in members if m not in pending]
    why = {m: "already connected" if states.get(m) == "connected" else "not installed" for m in others}
    hint = " and ".join(MEMBER_WORDS.get(m, m) for m in pending) + " (" + ", ".join(f"{MEMBER_WORDS.get(m, m)} {why[m]}" for m in others) + ")"
    return Option(row, LABELS[row], hint=hint)


RESTART_WORDS = {"claude_desktop": "Claude Desktop"}
RESTART_HOW = {"macos": "quit it (Cmd-Q) and open it again", "windows": "quit it (File > Exit, or from the tray) and open it again"}


def restart_needed(ctx: Context, doc: dict[str, Any]) -> list[str]:
    """Clients that have been open since before the kit last wrote their config: they read it only at launch, so the
    kit's server is not loaded in them yet, whatever the config says."""
    stale: list[str] = []
    for artifact in doc.get("artifacts") or []:
        client = str(artifact.get("client") or "")
        if client not in RESTART_WORDS or artifact.get("removed_at") or client in stale:
            continue
        try:
            changed = Path(str(artifact.get("path"))).stat().st_mtime
        except OSError:
            continue
        started = app_started_at(ctx.runner, ctx.platform.os, client)
        if started is not None and started < changed:
            stale.append(client)
    return stale


def _say_restart(ctx: Context, stale: list[str]) -> None:
    how = RESTART_HOW.get(ctx.platform.os, "quit it and open it again")
    for client in stale:
        ctx.ui.warn(f"{RESTART_WORDS[client]} has been open since before its MCP config changed, so it has not loaded the "
                    f"exasol server yet: {how}.")


def _mark_restart(ctx: Context, doc: dict[str, Any]) -> None:
    """The doctor's answer names a client that must be reopened, as a warning finding and under details.restart_needed."""
    stale = restart_needed(ctx, doc)
    if not stale:
        return
    doc.setdefault("details", {})["restart_needed"] = stale
    how = RESTART_HOW.get(ctx.platform.os, "quit it and open it again")
    doc.setdefault("findings", []).extend(
        {"code": "client_restart_needed", "severity": "warning", "scope": client,
         "message": f"{RESTART_WORDS[client]} has been open since before its MCP config changed, so it has not loaded the exasol server yet: {how}."}
        for client in stale)
    if doc.get("status") == "success":
        doc["status"] = "success_with_warnings"
