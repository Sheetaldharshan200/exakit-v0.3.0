"""AI clients over MCP: the read-only database user, client configuration, status, doctor, removal.

The kit's ``mcp`` package (through ``adapters.clients``) owns the client
config files; this module owns the database side (the dedicated read-only
user and its posture), the selection, the screens and the manifest record.
"""

from __future__ import annotations

from typing import Any

from exakit.adapters.clients import CLIENT_IDS, ClientCall, client_states, managed_clients
from exakit.adapters.exapump import Exapump, Profile, has_token, temp_config
from exakit.adapters.fs.credentials import CredentialStore
from exakit.domain.errors import BadInput, Failed, NotInstalled, NotRunning
from exakit.domain.ids import CLIENT_WORDS_HELP, is_skip_word, parse_client_selection
from exakit.domain.result import Result
from exakit.ui.widgets import Option

from . import Context
from .machine import kit_root
from .runtime_ops import credentials, ensure_running, exapump, is_running, runtime_remedy

LABELS = {"claude_desktop": "Claude", "claude_code": "Claude Code (CLI)", "cursor": "Cursor", "codex": "Codex",
          "vscode_copilot": "GitHub Copilot", "gemini_cli": "Gemini CLI", "opencode": "OpenCode", "continue": "Continue"}
READONLY_USER_DEFAULT = "mcp_readonly"
READONLY_SCHEMAS_DEFAULT = "STARTER_KIT"
REPAIRABLE_CODES = {"permission_drift", "manifest_drift_hash_mismatch", "manifest_drift_missing_artifact",
                    "managed_artifact_missing", "managed_entry_outdated"}


def _clients(ctx: Context):
    if ctx.clients is None:
        from exakit.adapters.clients import InProcessClientOps  # noqa: PLC0415
        ctx.clients = InProcessClientOps(kit_root(ctx))
    return ctx.clients


# --- the read-only user ----------------------------------------------------------


def _die_missing(what: str, ctx: Context) -> Failed:
    return Failed(f"The install record is incomplete (no {what} recorded), so the read-only login for your AI client cannot be created. "
                  f"Re-run the installer to rebuild it: {ctx.install_command()}", remedy=ctx.install_command())


def configure_readonly_access(ctx: Context) -> None:
    """Create or refresh the dedicated read-only user, grant, validate, and assert its posture."""
    manifest = ctx.manifest()
    pump = exapump(ctx)
    if pump is None:
        raise Failed("exapump is required for MCP read-only setup but was not found.", remedy="exakit update")
    admin_user = manifest.get("runtime.user")
    if not admin_user:
        raise _die_missing("database user", ctx)
    pw_file = manifest.get("runtime.password_file")
    admin_password = credentials(ctx).read(pw_file.rsplit("/", 1)[-1]) if pw_file else None
    if not admin_password:
        raise Failed("No runtime database password is available (runtime.password_file is missing). Re-run the installer to rebuild it.",
                     remedy=ctx.install_command())
    dsn = manifest.get("runtime.dsn") or ""
    host, _, port_text = dsn.rpartition(":")
    if not host or not port_text.isdigit():
        raise _die_missing("database address", ctx)
    ro_user = (ctx.env.get("EXAKIT_MCP_READONLY_USER") or READONLY_USER_DEFAULT).upper()
    if not ro_user.replace("_", "").isalnum():
        raise BadInput(f"Invalid EXAKIT_MCP_READONLY_USER: {ro_user}")
    schema = (ctx.env.get("EXAKIT_MCP_READONLY_SCHEMAS") or READONLY_SCHEMAS_DEFAULT).split(",")[0].strip().upper()
    store = credentials(ctx)
    ro_password = store.read("mcp_readonly_password")
    if not CredentialStore.is_token(ro_password):
        ro_password = CredentialStore.new_token()
        store.store("mcp_readonly_password", ro_password)
    profiles = [Profile("admin", host, int(port_text), admin_user, admin_password),
                Profile("mcp_readonly", host, int(port_text), ro_user, ro_password, schema=schema)]
    with temp_config(ctx.paths.cache, profiles) as config:
        def admin(sql: str):
            return pump.sql("admin", sql, config=config)

        def must(done, message: str) -> None:
            if not done.ok:
                ctx.log.line("ERROR", f"{message}: {done.err.strip()[-300:] or done.out.strip()[-300:]}")
                raise Failed(message, remedy="exakit mcp-setup")

        probe = admin(f"SELECT CASE WHEN EXISTS (SELECT 1 FROM EXA_DBA_USERS WHERE USER_NAME = '{ro_user}') "
                      "THEN 'EXAKIT_MCP_USER_PRESENT' ELSE 'EXAKIT_MCP_USER_MISSING' END AS STATUS")
        must(probe, "Could not read the database's user list.")
        if "EXAKIT_MCP_USER_PRESENT" not in probe.out:
            ctx.ui.info(f"Creating the dedicated MCP read-only database user ({ro_user.lower()})")
            must(admin(f"CREATE USER {ro_user} IDENTIFIED BY \"{ro_password}\""), "Could not create the MCP read-only database user.")
        must(admin(f"ALTER USER {ro_user} IDENTIFIED BY \"{ro_password}\""), "Could not refresh the MCP read-only database password.")
        must(admin(f"GRANT CREATE SESSION TO {ro_user}"), "Could not grant CREATE SESSION to the MCP read-only user.")
        schema_probe = admin(f"SELECT CASE WHEN EXISTS (SELECT 1 FROM EXA_ALL_SCHEMAS WHERE SCHEMA_NAME = '{schema}') "
                             "THEN 'EXAKIT_SCHEMA_PRESENT' ELSE 'EXAKIT_SCHEMA_MISSING' END AS STATUS")
        if "EXAKIT_SCHEMA_PRESENT" not in schema_probe.out:
            ctx.ui.info(f"Creating default schema {schema} for MCP-safe querying")
            must(admin(f"CREATE SCHEMA {schema}"), f"Could not create the default schema {schema}.")
        must(admin(f"GRANT USE ANY SCHEMA TO {ro_user}"), "Could not grant USE ANY SCHEMA to the MCP read-only user.")
        must(admin(f"GRANT SELECT ANY TABLE TO {ro_user}"), "Could not grant SELECT ANY TABLE to the MCP read-only user.")
        ctx.ui.info("Validating dedicated MCP read-only login")
        login = pump.sql("mcp_readonly", "SELECT CURRENT_USER AS EXAKIT_CURRENT_USER", config=config)
        if not login.ok or ro_user not in login.out.upper():
            raise Failed("The MCP read-only user could not log in with the generated credentials.", remedy="exakit mcp-setup")
        if not has_token(pump.sql("mcp_readonly", "SELECT 'EXAKIT_MCP_READONLY_OK' AS STATUS", config=config), "EXAKIT_MCP_READONLY_OK"):
            raise Failed("The MCP read-only user did not pass the validation query.", remedy="exakit mcp-setup")
        assert_readonly_posture(pump, config, ro_user, schema)

    def change(m) -> None:
        m.set("components.mcp_server.connection.user", ro_user.lower())
        m.set("components.mcp_server.connection.password_file", str(store.path("mcp_readonly_password")))
        m.set("components.mcp_server.connection.schemas", [schema])
        m.set("components.mcp_server.connection.default_schema", schema)
        m.set("components.mcp_server.connection.read_scope",
              "every schema (USE ANY SCHEMA + SELECT ANY TABLE); 'schemas' is the connection default, not a limit")
        m.set("components.mcp_server.connection.validated", True)
    ctx.manifest_store.update(change)
    ctx.ui.ok("Dedicated MCP read-only access is configured and validated")


def assert_readonly_posture(pump: Exapump, config, ro_user: str, schema: str) -> None:
    """The six grant checks plus a live write probe; any failure stops setup to protect the database."""
    checks = [
        (f"SELECT CASE WHEN EXISTS (SELECT 1 FROM EXA_DBA_SYS_PRIVS WHERE GRANTEE='{ro_user}' AND PRIVILEGE='CREATE SESSION') THEN 'EXAKIT_CREATE_SESSION_OK' ELSE 'MISSING' END", "EXAKIT_CREATE_SESSION_OK", "CREATE SESSION is not granted"),
        (f"SELECT CASE WHEN EXISTS (SELECT 1 FROM EXA_DBA_SYS_PRIVS WHERE GRANTEE='{ro_user}' AND PRIVILEGE='USE ANY SCHEMA') THEN 'EXAKIT_USE_ANY_SCHEMA_OK' ELSE 'MISSING' END", "EXAKIT_USE_ANY_SCHEMA_OK", "USE ANY SCHEMA is not granted"),
        (f"SELECT CASE WHEN EXISTS (SELECT 1 FROM EXA_DBA_SYS_PRIVS WHERE GRANTEE='{ro_user}' AND PRIVILEGE='SELECT ANY TABLE') THEN 'EXAKIT_SELECT_ANY_TABLE_OK' ELSE 'MISSING' END", "EXAKIT_SELECT_ANY_TABLE_OK", "SELECT ANY TABLE is not granted"),
        (f"SELECT CASE WHEN (SELECT COUNT(*) FROM EXA_DBA_SYS_PRIVS WHERE GRANTEE='{ro_user}' AND PRIVILEGE NOT IN ('CREATE SESSION','USE ANY SCHEMA','SELECT ANY TABLE'))=0 THEN 'EXAKIT_SYS_PRIV_SCOPE_OK' ELSE 'EXTRA' END", "EXAKIT_SYS_PRIV_SCOPE_OK", "the read-only user holds extra system privileges"),
        (f"SELECT CASE WHEN (SELECT COUNT(*) FROM EXA_DBA_ROLE_PRIVS WHERE GRANTEE='{ro_user}' AND GRANTED_ROLE NOT IN ('PUBLIC'))=0 THEN 'EXAKIT_ROLE_SCOPE_OK' ELSE 'EXTRA' END", "EXAKIT_ROLE_SCOPE_OK", "the read-only user holds extra roles"),
        (f"SELECT CASE WHEN (SELECT COUNT(*) FROM EXA_DBA_OBJ_PRIVS WHERE GRANTEE='{ro_user}' AND PRIVILEGE <> 'SELECT')=0 THEN 'EXAKIT_OBJ_PRIV_SCOPE_OK' ELSE 'EXTRA' END", "EXAKIT_OBJ_PRIV_SCOPE_OK", "the read-only user holds non-SELECT object privileges"),
    ]
    for sql, token, problem in checks:
        if not has_token(pump.sql("admin", sql, config=config), token):
            raise Failed(f"Security check failed: {problem}. Setup stopped to protect your database.", remedy="exakit mcp-setup")
    probe = pump.sql("mcp_readonly", f"CREATE TABLE {schema}.EXAKIT_MCP_PERMISSION_PROBE (ID DECIMAL)", config=config)
    if probe.ok:
        pump.sql("admin", f"DROP TABLE {schema}.EXAKIT_MCP_PERMISSION_PROBE", config=config)
        raise Failed(f"Security check failed: the MCP read-only user was able to write to schema {schema}, but it must be read-only. "
                     "Setup stopped to protect your database.", remedy="exakit mcp-setup")


# --- selection and setup --------------------------------------------------------------


def detected_clients(ctx: Context) -> dict[str, str] | None:
    return client_states(_clients(ctx).discover(ctx.paths.home))


def _select(ctx: Context) -> list[str] | None:
    """The clients to configure: from the environment, or the interactive menu. None means nothing to do."""
    raw = ctx.env.get("EXAKIT_MCP_CLIENTS", "")
    if raw:
        if is_skip_word(raw):
            ctx.ui.info(f"Skipping AI client setup (EXAKIT_MCP_CLIENTS={raw}) - run 'exakit mcp-setup' any time.")
            return None
        try:
            chosen = parse_client_selection(raw)
        except BadInput:
            ctx.ui.warn(f"EXAKIT_MCP_CLIENTS='{raw}' is not valid (use {CLIENT_WORDS_HELP}, or numbers 1-7).")
            raise
        if raw.strip().lower() == "all":
            states = detected_clients(ctx)
            if states:
                present = [c for c in chosen if states.get(c) in ("connected", "pending")]
                skipped = [c for c in chosen if c not in present]
                if present:
                    chosen = present
                    if skipped:
                        ctx.ui.info(f"EXAKIT_MCP_CLIENTS=all - not installed here, skipped: {','.join(skipped)} (name one explicitly to configure it anyway)")
        ctx.ui.info(f"Configuring MCP clients from EXAKIT_MCP_CLIENTS: {','.join(chosen)}")
        return chosen
    states = detected_clients(ctx) or {c: "pending" for c in CLIENT_IDS}
    pending = [c for c in CLIENT_IDS if states.get(c) == "pending"]
    if not pending:
        if not any(s == "connected" for s in states.values()):
            ctx.ui.info("No AI client was found on this machine, so there is nothing to connect yet.")
            ctx.ui.info("Install one (Claude, Codex, Cursor, Copilot, Gemini CLI, OpenCode, Continue) and run 'exakit mcp-setup'.")
        else:
            ctx.ui.ok("All AI clients found on this machine are already connected over MCP.")
            ctx.ui.info("Check them with 'exakit mcp-status'; new clients appear here once installed.")
        return None
    options = []
    for cid in CLIENT_IDS:
        state = states.get(cid, "missing")
        hint = "already connected" if state == "connected" else "not installed" if state == "missing" else ""
        options.append(Option(cid, LABELS[cid], hint=hint, disabled=state != "pending"))
    chosen = ctx.ui.checkboxes("AI clients to connect", options, defaults=pending)
    if not chosen:
        ctx.ui.info("No AI client selected - connect one any time with: exakit mcp-setup")
        return None
    return chosen


def setup(ctx: Context) -> Result:
    """``exakit mcp-setup``: heal the database, provision the read-only user, write the client configs."""
    ensure_running(ctx)
    ctx.ui.info("MCP setup will edit the selected AI client config files.")
    chosen = _select(ctx)
    if chosen is None:
        return Result(True, "skipped", data={"configured_clients": [], "skipped_clients": []})
    configure_readonly_access(ctx)
    ctx.ui.info("Applying MCP setup")
    call = _clients(ctx).setup(ctx.paths.home, chosen)
    return _report_setup(ctx, call, chosen)


def _report_setup(ctx: Context, call: ClientCall, chosen: list[str]) -> Result:
    doc = call.doc or {}
    details = doc.get("details") or {}
    configured = list(details.get("configured_clients") or [])
    skipped = details.get("skipped_clients") or []
    status = doc.get("status", "failed")
    if call.code != 0 and not configured:
        ctx.log.line("ERROR", f"mcp setup: {call.stderr.strip()[-400:]}")
        raise Failed("Could not write the MCP entry for this AI client. What failed: exakit logs setup. Retry with: exakit mcp-setup",
                     remedy="exakit mcp-setup")
    labels = ", ".join(LABELS.get(c, c) for c in configured) or "no clients"
    if str(status).startswith("success"):
        ctx.ui.ok(f"MCP configured for {labels}")
    else:
        ctx.ui.warn(f"MCP setup finished as '{status}' for {labels}")
    for skip in skipped:
        ctx.ui.warn(f"Skipped {LABELS.get(skip.get('client'), skip.get('client'))}: {skip.get('reason')}")
    for finding in doc.get("findings") or []:
        if finding.get("code") == "plaintext_credential_reference":
            ctx.log.line("INFO", finding.get("message", ""))
        elif finding.get("severity") == "info":
            ctx.ui.info(finding.get("message", ""))
        else:
            ctx.ui.warn(finding.get("message", ""))
    manifest = ctx.manifest()
    dsn, user = manifest.get("runtime.dsn"), manifest.get("components.mcp_server.connection.user") or "mcp_readonly"
    ctx.ui.ok(f"MCP server 'exasol' - {dsn} as {user} (read-only), started by your AI client on demand")
    ctx.log.line("INFO", "Config file paths and per-client state: exakit mcp-status")
    data = {"configured_clients": configured, "skipped_clients": [s.get("client") for s in skipped], "mcp_status": status}
    return Result(True, "configured" if configured else "partial", data=data, exit_code=0 if configured else 1)


# --- status, doctor, remove ---------------------------------------------------------------


def _stamp(doc: dict[str, Any]) -> dict[str, Any]:
    """Add ``installed`` and the best ``remedy`` (the most severe finding's recommended action)."""
    doc.setdefault("installed", True)
    rank = {"critical": 0, "error": 1, "warning": 2}
    best = None
    for index, finding in enumerate(doc.get("findings") or []):
        severity = finding.get("severity")
        action = finding.get("recommended_action")
        if severity in rank and action:
            key = (rank[severity], 0 if finding.get("scope") else 1, index)
            if best is None or key < best[0]:
                best = (key, action)
    doc["remedy"] = best[1] if best else None
    return doc


def _clients_from_args(args: list[str]) -> list[str]:
    if not args:
        return []
    try:
        return parse_client_selection(" ".join(args))
    except BadInput:
        raise BadInput("Please choose valid AI clients: claude, claude_desktop, claude_code, codex, cursor, copilot, gemini, opencode, continue, or all.")


def status(ctx: Context, args: list[str]) -> Result:
    ctx.manifest()
    clients = _clients_from_args(args)
    call = _clients(ctx).operation("status", ctx.paths.home, clients)
    if call.doc is None:
        raise Failed("the MCP status operation produced no result; what it printed is in: exakit logs setup", remedy="exakit logs setup")
    doc = _stamp(dict(call.doc))
    if not ctx.json:
        _render_status(ctx, doc)
    return Result(True, str(doc.get("status", "unknown")), remedy=doc.get("remedy"), data=doc, raw=True,
                  exit_code=0 if call.code == 0 else 1)


def _render_status(ctx: Context, doc: dict[str, Any]) -> None:
    rows = (doc.get("details") or {}).get("clients") or []
    configured = [r for r in rows if r.get("state") == "configured"]
    home = ctx.env.get("HOME") or ""
    lines = [f"{'Client':<20} {'State':<12} Config"]
    for row in configured:
        path = str(row.get("path") or "")
        if home and path.startswith(home):
            path = "~" + path[len(home):]
        lines.append(f"{LABELS.get(row['client'], row['client']):<20} {'configured':<12} {path}")
    if not configured:
        lines.append("Nothing configured yet. Connect a client with: exakit mcp-setup")
    ctx.ui.panel("MCP clients", lines)
    notes = [f.get("message", "") for f in doc.get("findings") or []]
    if notes:
        ctx.ui.text("  Notes:")
        for note in notes:
            ctx.ui.text(f"  - {note}")


def doctor(ctx: Context, args: list[str]) -> Result:
    manifest = ctx.manifest_or_none()
    if manifest is None:
        raise NotInstalled("No installation found.", remedy=ctx.install_command())
    if not manifest.runtime_type():
        raise NotRunning("No runtime is recorded in the manifest yet, so there is no database to diagnose against.",
                         remedy=ctx.install_command(), hint="no runtime is recorded yet; the installer resumes at the unfinished step",
                         data={"installed": True, "status": "no database", "database": "not installed"})
    if not is_running(ctx):
        remedy = runtime_remedy(ctx)
        raise NotRunning(f"The database is not running - fix that first: {remedy}", remedy=remedy,
                         hint="MCP diagnostics need a live database (the read-only user and its grants are checked against it)",
                         data={"installed": True, "status": "stopped", "database": "not running"})
    clients = _clients_from_args(args)
    configure_readonly_access(ctx)
    call = _clients(ctx).operation("doctor", ctx.paths.home, clients)
    if call.doc is None:
        raise Failed("Could not run MCP diagnostics", remedy="exakit logs setup")
    doc = _stamp(dict(call.doc))
    repairable = any(f.get("code") in REPAIRABLE_CODES and f.get("severity") in ("warning", "error", "critical")
                     for f in doc.get("findings") or [])
    if not ctx.json:
        _render_operation(ctx, doc)
        if repairable:
            ctx.ui.info("Repairing the managed client config - re-checking")
            repair = _clients(ctx).operation("repair", ctx.paths.home, clients)
            if repair.doc and repair.doc.get("status") == "no_change":
                ctx.ui.info("Nothing to repair: the managed client config is already consistent.")
            recheck = _clients(ctx).operation("doctor", ctx.paths.home, clients)
            doc = _stamp(dict(recheck.doc or doc))
            call = recheck
            if recheck.code == 0:
                ctx.ui.ok("Everything the repair could fix is fixed.")
            else:
                ctx.ui.warn("Some findings are not config drift and remain - see the notes above.")
        ctx.ui.info("Connect or re-connect AI clients any time with:  exakit mcp-setup")
    return Result(True, str(doc.get("status", "unknown")), remedy=doc.get("remedy"), data=doc, raw=True,
                  exit_code=0 if call.code == 0 else 1)


def _render_operation(ctx: Context, doc: dict[str, Any]) -> None:
    ctx.ui.text("")
    ctx.ui.text("  MCP operation summary")
    ctx.ui.text(f"  Operation: {doc.get('operation')}")
    ctx.ui.text(f"  Status:    {doc.get('status')}")
    ctx.ui.text(f"  Summary:   {doc.get('summary')}")
    states = (doc.get("details") or {}).get("clients") or []
    if states:
        ctx.ui.text("  Client state:")
        groups: dict[str, list[str]] = {}
        for row in states:
            groups.setdefault(str(row.get("state")), []).append(LABELS.get(row.get("client"), str(row.get("client"))))
        for state, names in groups.items():
            ctx.ui.text(f"    {state.replace('_', ' '):<26} {', '.join(names)}")
    findings = doc.get("findings") or []
    if findings:
        ctx.ui.text("  Notes:")
        for finding in findings:
            ctx.ui.text(f"  - {finding.get('message')}")
    actions = doc.get("next_actions") or []
    if actions:
        ctx.ui.text("  Next:")
        for action in actions:
            ctx.ui.text(f"  - {action.get('message')}")


def remove(ctx: Context, args: list[str]) -> Result:
    if not args:
        raise BadInput("Name the client(s) to remove the kit's MCP entries from: exakit mcp-remove cursor (see: exakit mcp-status)")
    if any(a.lower() == "all" for a in args):
        raise BadInput("mcp-remove takes client names, not 'all' - the full removal is: exakit uninstall")
    ctx.manifest()
    clients = _clients_from_args(args)
    call = _clients(ctx).operation("uninstall", ctx.paths.home, clients)
    if call.doc is None or call.code not in (0,) and (call.doc or {}).get("status") not in ("no_change",):
        raise Failed("Could not remove the MCP entries", remedy="exakit mcp-status")
    doc = _stamp(dict(call.doc))
    if not ctx.json:
        _render_operation(ctx, doc)
        for change in doc.get("changes") or []:
            ctx.ui.text(f"  - {change.get('kind')} {change.get('path')}")
    return Result(True, str(doc.get("status")), remedy=doc.get("remedy"), data=doc, raw=True)


# --- add-on endpoints and pin refresh ----------------------------------------------------


def managed(ctx: Context) -> list[str]:
    return managed_clients(_clients(ctx).operation("status", ctx.paths.home, []))


def register_addon_servers(ctx: Context, label: str) -> bool:
    clients = managed(ctx)
    if not clients:
        ctx.ui.info("No AI client is connected yet - connect one any time with: exakit mcp-setup")
        return True
    call = _clients(ctx).register_addon_servers(ctx.paths.home, clients)
    if call.code != 0:
        ctx.ui.warn(f"Could not register the {label} MCP endpoint with your AI clients - run: exakit mcp-setup")
        return False
    configured = ((call.doc or {}).get("dash_server") or {}).get("configured_clients") or []
    if configured:
        ctx.log.line("OK", f"{label} MCP endpoint registered with: {','.join(configured)}")
    else:
        ctx.ui.info(f"No connected AI client can take a remote MCP endpoint - drive {label} with: exakit help {label}")
    return True


def unregister_server_entry(ctx: Context, server: str, label: str) -> bool:
    clients = managed(ctx)
    if not clients:
        return True
    call = _clients(ctx).operation("uninstall", ctx.paths.home, clients, servers=[server])
    if call.code != 0:
        ctx.ui.warn(f"The {label} MCP entry may still be in your AI client configs - check with: exakit mcp-status")
        return False
    return True


def refresh_client_pins(ctx: Context, version: str) -> bool:
    clients = managed(ctx)
    if not clients:
        ctx.ui.info("No AI client is connected yet - connect one any time with: exakit mcp-setup")
        return True
    ctx.ui.info(f"Refreshing AI client configs to exasol-mcp-server@{version}")
    configure_readonly_access(ctx)
    call = _clients(ctx).setup(ctx.paths.home, clients)
    if call.code != 0:
        ctx.ui.warn("Could not refresh the AI client configs - run exakit mcp-setup to finish the update.")
        return False
    ctx.ui.ok(f"AI client configs now launch exasol-mcp-server@{version}")
    return True
