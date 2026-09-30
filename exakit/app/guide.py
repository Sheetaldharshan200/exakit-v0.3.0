"""``exakit guide``: how to connect, three doors; and the two Kit 2 scripts the kit carries, run from its own copy."""

from __future__ import annotations

from exakit.domain.errors import Failed
from exakit.domain.result import Result
from exakit.ui.widgets import tilde

from . import Context
from .machine import kit_root


def run(ctx: Context) -> Result:
    manifest = ctx.manifest()
    home = ctx.env.get("HOME", "")
    dsn = manifest.get("runtime.dsn") or ""
    host, _, port = dsn.rpartition(":")
    host, port = host or "127.0.0.1", port or "8563"
    user = manifest.get("runtime.user") or "sys"
    pw_file = manifest.get("runtime.password_file")
    ro_user = manifest.get("components.mcp_server.connection.user")
    ctx.ui.banner("How to connect", "AI clients, SQL clients, Python - pick your door")
    ctx.ui.panel("1 · Ask questions with an AI client (MCP)", [
        "Connect one or more AI clients in a single guided step:", "  exakit mcp-setup",
        "Supported: Claude, Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI, OpenCode, Continue",
        "Then restart/reload the client and look for the MCP server 'exasol'.", "",
        "First thing to ask it:", '  "List the schemas and tables in my Exasol database, then answer my',
        '   questions with read-only SQL - show me the SQL before you run it."',
        "14 ready-made questions: data/example-questions.md (in the kit)"])
    sql = ["Both free: DBeaver (https://dbeaver.io/download/) or DbVisualizer (https://www.dbvis.com/download/)", "",
           "In DBeaver: Database > New Database Connection > search 'Exasol'",
           f"  Host:      {host}", f"  Port:      {port}", f"  User:      {user}"]
    if pw_file:
        sql.append(f"  Password:  cat {tilde(str(pw_file), home)}")
    if ro_user:
        sql.append(f"  (read-only alternative: user {ro_user})")
    sql += ["  TLS:       local self-signed certificate - in Driver properties set",
            "             validateservercertificate = 0 (or add ;validateservercertificate=0",
            "             to the JDBC URL), then Test Connection > Finish.",
            "Each bundled dataset has its own schema (TPCH, ENERGY, WEATHER);", "your own uploads default to STARTER_KIT."]
    ctx.ui.panel("2 · Browse and query with a SQL client (GUI)", sql)
    ctx.ui.panel("3 · Terminal and Python", [
        "Interactive SQL shell:   exapump interactive -p starter-kit", 'One-off query:           exapump sql -p starter-kit "SELECT 42"', "",
        "Python (pyexasol preinstalled in its own environment):", f"  {tilde(str(ctx.paths.home / 'pyexasol-venv' / 'bin' / 'python'), home)}",
        "  import pyexasol", f"  c = pyexasol.connect(dsn='{host}:{port}', user='{user}',",
        "                       password=open('<password file above>').read(),", "                       websocket_sslopt={'cert_reqs': 0})",
        "  c.export_to_pandas('SELECT * FROM TPCH.CUSTOMER LIMIT 5')"])
    ctx.ui.panel("Everything else", ["Connection summary:   exakit info", "Load more data:       exakit data-load",
                                     "Optional add-ons:     exakit marketplace (dashboards & more)", "Health check:         exakit status · exakit mcp-doctor"])
    ctx.ui.text("")
    return Result(True, "ok")


def kit2_script(ctx: Context, name: str) -> Result:
    """``exakit upgrade-kit2`` / ``rollback-kit2``: the kit's own upgrade scripts, from the installed copy, no path to type."""
    script = kit_root(ctx) / "upgrade" / name
    if not script.is_file():
        raise Failed(f"{name} is not part of this kit build.")
    code = ctx.runner.interactive(["bash", str(script)], env=dict(ctx.env))
    if code != 0:
        raise Failed(f"{name} reported an error (exit {code}).")
    return Result(True, "ok")
