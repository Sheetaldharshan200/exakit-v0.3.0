"""The migrated commands: parse their own options, call a use case, return a Result.

Each function takes the raw argument list after the command word and the
Context. Options are the legacy ones, refused with the legacy wording.
"""

from __future__ import annotations

import sys

from exakit.app import Context, help as help_app, persona as persona_app, skills as skills_app, version as version_app, whats_new
from exakit.app.machine import kit_root
from exakit.domain.errors import BadInput
from exakit.domain.result import Result
from exakit.ui.widgets import term_cols

JSON_FLAGS = ("--json", "-j")


def _split(args: list[str], allowed: tuple[str, ...], command: str) -> tuple[list[str], set[str]]:
    """Positional arguments and the flags seen; an unknown flag is refused the legacy way."""
    positional, flags = [], set()
    for arg in args:
        if arg.startswith("-"):
            if arg not in allowed:
                supported = ", ".join(a for a in allowed if a.startswith("--")) or "none"
                raise BadInput(f"Unknown option '{arg}' for {command} (supported: {supported}).")
            flags.add(arg)
        else:
            positional.append(arg)
    return positional, flags


def _help_docs(ctx: Context):
    return help_app.load_docs(kit_root(ctx) / "setup" / "help")


def _help_color(ctx: Context) -> bool:
    return sys.stdout.isatty() and ctx.env.get("EXAKIT_HELP_PLAIN") != "1" and not ctx.json


# --- help / catalog / whats-new ---------------------------------------------------


def help_command(args: list[str], ctx: Context) -> Result:
    positional, flags = _split(args, JSON_FLAGS + ("--all", "-a", "--help", "-h"), "help")
    docs = _help_docs(ctx)
    topic = positional[0] if positional else ""
    if ctx.json:
        return Result(True, "ok", data=help_app.json_payload(docs, topic or "all"), raw=True)
    if "--all" in flags or "-a" in flags:
        mode, arg = "all", ""
    elif topic and topic in docs:
        mode, arg = "component", topic
    elif topic:
        mode, arg = "command", topic
    else:
        mode, arg = "overview", ""
    text, rc = help_app.render(docs, mode, arg, color=_help_color(ctx), width=term_cols())
    sys.stdout.write(text)
    return Result(True, "ok", exit_code=rc)


def topic_help(topic: str, ctx: Context) -> Result:
    """``exakit <command> --help`` and ``exakit <component>``: the page for one topic."""
    docs = _help_docs(ctx)
    mode = "component" if topic in docs else "command"
    text, rc = help_app.render(docs, mode, topic, color=_help_color(ctx), width=term_cols())
    sys.stdout.write(text)
    return Result(True, "ok", exit_code=rc)


def is_help_topic(topic: str, ctx: Context) -> bool:
    return topic in _help_docs(ctx)


def catalog_command(args: list[str], ctx: Context) -> Result:
    positional, _ = _split(args, JSON_FLAGS, "catalog")
    docs = _help_docs(ctx)
    search = " ".join(positional)
    if ctx.json:
        return Result(True, "ok", data=help_app.json_payload(docs, search or "all"), raw=True)
    text, rc = help_app.render(docs, "catalog", search, color=_help_color(ctx), width=term_cols())
    sys.stdout.write(text)
    return Result(True, "ok", exit_code=rc)


def whats_new_command(args: list[str], ctx: Context) -> Result:
    positional, _ = _split(args, JSON_FLAGS, "whats-new")
    return whats_new.run(ctx, positional[0] if positional else None)


# --- version --------------------------------------------------------------------------


def version_command(args: list[str], ctx: Context) -> Result:
    _split(args, JSON_FLAGS, "version")
    return version_app.run(ctx)


# --- persona ----------------------------------------------------------------------------


def persona_command(args: list[str], ctx: Context) -> Result:
    positional, flags = _split(args, JSON_FLAGS + ("--yes", "-y"), "persona")
    sub = positional[0] if positional else ""
    pid = positional[1] if len(positional) > 1 else ""
    if len(positional) > 2:
        raise BadInput(f"Too many arguments for persona: '{positional[2]}'.")
    if sub not in ("", "list", "show", "plan", "apply"):
        raise BadInput(f"Unknown persona subcommand '{sub}' (use list, show <id>, plan <id>, or apply <id>).")
    if (ctx.yes or "--yes" in flags or "-y" in flags) and sub != "apply":
        raise BadInput("--yes only applies to: exakit persona apply <id> --yes")
    if sub in ("show", "plan", "apply") and not pid:
        raise BadInput(f"persona {sub} needs an id (see: exakit persona list).")
    if sub in ("", "list") and pid:
        raise BadInput(f"persona list takes no id (did you mean: exakit persona show {pid}).")
    if pid:
        ctx.catalog.persona(pid)   # unknown id -> BadInput naming the known ones
    if sub == "list" or (sub == "" and (ctx.json or not ctx.ui.interactive)):
        result = persona_app.list_personas(ctx)
        if sub == "" and not ctx.json:
            ctx.ui.info("Without a terminal nothing is installed. Apply one with: exakit persona apply <id> --yes")
        return result
    if sub == "show":
        return persona_app.show(ctx, pid)
    if sub == "plan":
        return persona_app.plan(ctx, pid)
    raise BadInput("exakit persona apply arrives with the next kit update; today: exakit persona plan <id>, then "
                   "exakit data-load, exakit mcp-setup and exakit marketplace <id> for what it lists.",
                   remedy=f"exakit persona plan {pid}" if pid else "exakit persona list")


# --- skills -----------------------------------------------------------------------------


def skills_command(args: list[str], ctx: Context) -> Result:
    positional, _ = _split(args, JSON_FLAGS, "skills")
    if positional:
        raise BadInput(f"Unknown option '{positional[0]}' for skills (supported: --json).")
    return skills_app.list_skills(ctx)


def skills_install_command(args: list[str], ctx: Context) -> Result:
    _split(args, (), "skills-install")
    ctx.manifest()   # exit 4 without an install record
    return skills_app.skills_install_command(ctx)
