"""``exakit``: one entry point, one dispatch, one place errors become exit codes.

Global flags (``--json``/``-j``, ``--yes``/``-y``, ``--dry-run``) may appear
anywhere; the first bare word is the command. A command in
``MIGRATED_COMMANDS`` runs in Python; anything else is handed to the legacy
shell CLI unchanged (phases A to C). A bare component id renders its help
page, and ``<command> --help`` renders that command's page, as before.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from exakit.app import Context, notice
from exakit.domain.errors import BadInput, ExakitError
from exakit.domain.result import Result

from . import _context, commands, legacy

MIGRATED_COMMANDS: frozenset[str] = frozenset({"help", "catalog", "whats-new", "version", "persona"})
READONLY_COMMANDS: frozenset[str] = frozenset({"help", "catalog", "whats-new", "version", "status", "info",
                                               "skills", "logs", "mcp-status", "persona"})
HANDLERS: dict[str, Callable[[list[str], Context], Result]] = {
    "help": commands.help_command, "-h": commands.help_command, "--help": commands.help_command,
    "catalog": commands.catalog_command, "whats-new": commands.whats_new_command,
    "version": commands.version_command, "--version": commands.version_command, "-v": commands.version_command,
    "persona": commands.persona_command,
}
ALIASES = {"-h": "help", "--help": "help", "--version": "version", "-v": "version"}


def _parse(argv: list[str]) -> tuple[str, list[str], dict[str, bool]]:
    flags = {"json": False, "yes": False, "dry_run": False}
    command = ""
    rest: list[str] = []
    for arg in argv:
        if arg in ("--json", "-j"):
            flags["json"] = True
        elif arg in ("--yes", "-y"):
            flags["yes"] = True
        elif arg == "--dry-run":
            flags["dry_run"] = True
        elif not command:
            command = arg
        else:
            rest.append(arg)
    return command or "help", rest, flags


def _emit(result: Result, ctx: Context) -> None:
    if ctx.json:
        sys.stdout.write(result.to_json() + "\n")
        sys.stdout.flush()


def _emit_refusal(err: ExakitError, ctx: Context | None, json_mode: bool) -> None:
    if json_mode:
        import json as _json
        sys.stdout.write(_json.dumps(err.refusal()) + "\n")
        sys.stdout.flush()
        return
    if ctx is not None:
        ctx.ui.card(err.message, log_path=str(ctx.log.path) if ctx.log.path else None)
        if err.remedy:
            ctx.ui.info(f"Next: {err.remedy}")
    else:
        sys.stderr.write(f"\n  [x] {err.message}\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command, rest, flags = _parse(argv)
    command = ALIASES.get(command, command)
    ctx: Context | None = None
    try:
        # `exakit sql --help` is a query, not a help request; every other command answers its page.
        wants_page = command != "sql" and command not in ("help",) and any(a in ("--help", "-h") for a in rest)
        if command in MIGRATED_COMMANDS or command in HANDLERS or wants_page or command == "install":
            readonly = command in READONLY_COMMANDS or wants_page
            ctx = _context.build(json=flags["json"], yes=flags["yes"], dry_run=flags["dry_run"],
                                 readonly=readonly, mutating=not readonly)
            if wants_page:
                return commands.topic_help(command, ctx).exit_code
            if command in HANDLERS:
                result = HANDLERS[command](rest, ctx)
                _emit(result, ctx)
                notice.maybe_show(ctx, command)
                return result.exit_code
            return legacy.run(ctx, command, rest + _flag_args(flags))
        # Not migrated: a bare component id is its help page; everything else is the legacy CLI's.
        ctx = _context.build(json=flags["json"], yes=flags["yes"], dry_run=flags["dry_run"], readonly=True, mutating=False)
        if not rest and commands.is_help_topic(command, ctx) and command not in _LEGACY_WORDS:
            return commands.topic_help(command, ctx).exit_code
        return legacy.run(ctx, command, rest + _flag_args(flags))
    except ExakitError as err:
        _emit_refusal(err, ctx, flags["json"])
        return err.code
    except KeyboardInterrupt:
        return 130


_LEGACY_WORDS = frozenset({"status", "info", "update", "start", "stop", "sql", "logs", "skills", "marketplace",
                           "uninstall", "guide", "preflight", "repair-runtime", "migrate", "autostart", "data-load",
                           "mcp-setup", "mcp-doctor", "mcp-status", "mcp-remove", "skills-install",
                           "upgrade-kit2", "rollback-kit2"})


def _flag_args(flags: dict[str, bool]) -> list[str]:
    out = []
    if flags["json"]:
        out.append("--json")
    if flags["yes"]:
        out.append("--yes")
    return out


def unknown_command(command: str) -> BadInput:
    return BadInput(f"Unknown command '{command}'.", remedy="exakit catalog --json")
