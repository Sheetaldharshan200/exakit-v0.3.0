"""What the dashboard shows and does, as plain data and callables: the facade between the screens and the app layer (design 6.1a)."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from typing import Any

from exakit.app import Context
from exakit.app.addons import marketplace as marketplace_app, services as services_app
from exakit.app.kit import status as status_app, version as version_app
from exakit.app.kit import help as help_app
from exakit.app.machine import kit_root
from exakit.domain import ownership
from exakit.domain.errors import ExakitError
from exakit.domain.result import Result
from exakit.ui.silent import SilentRenderer

from . import commands

Job = Callable[[], Result]


class DashboardData:
    """Reads with a silent copy of the Context (a worker thread calls these); actions are the ordinary commands."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.quiet = dataclasses.replace(ctx, ui=SilentRenderer(), json=True)      # reads narrate nowhere, not even the log
        self._docs: dict[str, dict[str, Any]] | None = None

    @property
    def docs(self) -> dict[str, dict[str, Any]]:
        """The help documents, loaded once."""
        if self._docs is None:
            self._docs = help_app.load_docs(kit_root(self.ctx) / "help")
        return self._docs

    def status(self) -> dict[str, Any]:
        """``exakit status``'s answer, or the refusal's words."""
        try:
            result = status_app.run(self.quiet)
        except ExakitError as err:
            return {"status": err.message, "running": False, "remedy": err.remedy, "installed": False}
        return {**result.data, "status": result.status, "remedy": result.remedy, "installed": True}

    def info(self) -> dict[str, Any]:
        """The install record as ``exakit info --json`` answers it (DSN, users, password files, kit source); empty before an install."""
        manifest = self.ctx.manifest_or_none()
        return dict(manifest.doc) if manifest else {}

    def scheduler(self) -> dict[str, Any]:
        """What the scheduler's own tables say: tasks, enabled, the last run, failures in the last day; empty when it cannot be asked."""
        from exakit.app.db.runtime_ops import exapump, is_running, profile_name
        manifest = self.ctx.manifest_or_none()
        if not manifest or not manifest.get("components.exasol_scheduler.version"):
            return {}
        pump = exapump(self.quiet)
        if pump is None or not is_running(self.quiet):
            return {}
        schema = str(manifest.get("components.exasol_scheduler.schema") or "SCHED")
        sql = (f"SELECT 'EXAKIT_SCHED[' || (SELECT COUNT(*) FROM {schema}.SCHED_TASKS) || '|' || (SELECT COUNT(*) FROM {schema}.SCHED_TASKS WHERE \"ENABLED\")"
               f" || '|' || COALESCE((SELECT TO_CHAR(MAX(\"STARTED_AT\"), 'YYYY-MM-DD HH24:MI') FROM {schema}.SCHED_HISTORY), '-')"
               f" || '|' || COALESCE((SELECT \"STATUS\" FROM {schema}.SCHED_HISTORY ORDER BY \"STARTED_AT\" DESC LIMIT 1), '-')"
               f" || '|' || (SELECT COUNT(*) FROM {schema}.SCHED_HISTORY WHERE UPPER(\"STATUS\") NOT IN ('SUCCESS', 'OK')"
               f" AND \"STARTED_AT\" > ADD_HOURS(CURRENT_TIMESTAMP, -24)) || ']' AS R")
        done = pump.sql(profile_name(self.quiet), sql, timeout=30)
        match = re.search(r"EXAKIT_SCHED\[([^\]]*)\]", done.out) if done.ok else None
        if not match:
            return {}
        tasks, enabled, last_at, last_status, failures = [*match.group(1).split("|"), "", "", "", "", ""][:5]
        return {"tasks": tasks, "enabled": enabled, "last_run": last_at, "last_status": last_status, "failures_24h": failures, "schema": schema}

    def datasets(self) -> dict[str, Any]:
        """The bundled datasets with what the database holds of each, and the last load the record remembers."""
        from exakit.app.loading import data as data_app
        manifest = self.ctx.manifest_or_none()
        last = dict(manifest.get("data.last_load") or {}) if manifest else {}
        try:
            tables = data_app.listing(self.quiet) or {}
            done = data_app.loaded(self.quiet, tables=tables or None, heal=False)
        except ExakitError:
            tables, done = {}, set()
        items = []
        for ds in data_app.bundled(self.quiet):
            mine = {name: rows for name, rows in tables.items() if name.upper().startswith(f"{ds.schema.upper()}.")}
            items.append({"id": ds.id, "label": ds.label, "schema": ds.schema, "loaded": ds.id in done, "tables": sorted(mine), "rows": sum(mine.values())})
        return {"items": items, "last_load": last}

    def log_path(self) -> str | None:
        """The log file this run writes, for the job view's tail."""
        path = getattr(self.ctx.log, "path", None)
        return str(path) if path else None

    def versions(self) -> list[dict[str, Any]]:
        """``exakit version``'s rows."""
        try:
            return [row.to_dict() for row in version_app.rows(self.quiet, refresh=False)]
        except ExakitError:
            return []

    def catalog(self) -> list[dict[str, Any]]:
        """Every component and add-on with its help tagline and role and its version row."""
        by_id = {row["component"]: row for row in self.versions()}
        market = {row["id"]: row for row in self.marketplace()}
        entries = []
        for cid in self.ctx.catalog.component_ids():
            component = self.ctx.catalog.component(cid)
            entries.append(self._entry(cid, component.title, component.kind, False, by_id, platforms=component.platforms, requires=component.requires))
        self._mark_ownership(entries)
        for addon in self.ctx.catalog.addons():
            entry = self._entry(addon.id, addon.title, addon.kind, True, by_id, platforms=addon.platforms, requires=addon.requires,
                                launcher=addon.launcher)
            row = market.get(addon.id) or {}
            entry["market"] = row.get("state") or row.get("status") or ""
            entry["market_reason"] = row.get("reason") or ""
            if row.get("version") and entry["advertised"] in (None, "-"):
                entry["advertised"] = row["version"]
            entries.append(entry)
        return entries

    def _mark_ownership(self, entries: list[dict[str, Any]]) -> None:
        """The runtime entry says whose launcher and database they are, when either is not the kit's own."""
        manifest = self.ctx.manifest_or_none()
        if not manifest:
            return
        words = [f"{piece}: {ownership.describe(manifest, piece)}" for piece in ownership.PIECES if ownership.tag(manifest, piece) != ownership.KIT]
        for entry in entries:
            if entry["id"] == "personal" and words:
                entry["managed"] = "; ".join(words)

    def _entry(self, cid: str, title: str, kind: str, addon: bool, rows: dict[str, dict[str, Any]], **extra: Any) -> dict[str, Any]:
        doc = self.docs.get(cid) or {}
        row = rows.get(cid) or {}
        return {"id": cid, "title": title, "kind": kind, "addon": addon, "tagline": doc.get("tagline", ""), "role": doc.get("role", ""),
                "installed": row.get("installed_label") or row.get("installed") or "not installed", "advertised": row.get("advertised"),
                "status": row.get("status", "unknown"), "remedy": row.get("remedy"), "note": row.get("note") or row.get("platform_note"),
                "platforms": list(extra.get("platforms") or ()), "requires": list(extra.get("requires") or ()), "launcher": extra.get("launcher")}

    def marketplace(self) -> list[dict[str, Any]]:
        """The marketplace rows: state, version, reason."""
        try:
            return [{**row.to_dict(), "reason": row.reason, "title": row.addon.title} for row in marketplace_app.rows(self.quiet)]
        except ExakitError:
            return []

    def commands(self) -> list[dict[str, Any]]:
        """Every command with its options, summary and group."""
        doc = self.docs.get("exakit") or {}
        groups = {name: group["title"] for group in doc.get("groups", []) for name in group.get("commands", [])}
        return [{"command": c["command"], "options": c.get("options", ""), "summary": c.get("summary", ""), "group": groups.get(c["command"].split()[0], "")}
                for c in doc.get("commands", [])]

    def help_page(self, topic: str, width: int = 100) -> str:
        """A command's or component's help page as plain text, wrapped for ``width`` columns."""
        mode = "command" if any(c["command"].split()[0] == topic for c in (self.docs.get("exakit") or {}).get("commands", [])) else "component"
        text, _ = help_app.render(self.docs, mode, topic, color=False, width=width)
        return text

    def job(self, kind: str, target: str = "") -> Job:
        """An action as the ordinary command, or one service's start or stop through its hooks."""
        table: dict[str, Job] = {
            "marketplace": lambda: commands.marketplace_command([target], self.ctx),
            "update": lambda: commands.update_command([target] if target else [], self.ctx),
            "start": lambda: commands.start_command([], self.ctx),
            "stop": lambda: commands.stop_command([], self.ctx),
            "service-start": lambda: self._service(target, start=True),
            "service-stop": lambda: self._service(target, start=False),
            "data-load": lambda: self._data_load(target),
            "autostart": lambda: commands.autostart_command([], self.ctx),
            "mcp-doctor": lambda: commands.mcp_doctor_command([], self.ctx),
        }
        return table[kind]

    def _data_load(self, target: str) -> Result:
        """``dataset:<id>`` loads one bundled dataset, ``reload:<id>`` replaces it, ``path:<p>`` loads a file or folder, nothing opens the menu."""
        kind, _, value = target.partition(":")
        if kind in ("dataset", "reload") and value:
            before = self.ctx.env.get("EXAKIT_DATASETS")
            self.ctx.env["EXAKIT_DATASETS"] = value
            try:
                return commands.data_load_command(["--force"] if kind == "reload" else [], self.ctx)
            finally:
                if before is None:
                    self.ctx.env.pop("EXAKIT_DATASETS", None)
                else:
                    self.ctx.env["EXAKIT_DATASETS"] = before
        if kind == "path" and value:
            return commands.data_load_command([value], self.ctx)
        return commands.data_load_command([], self.ctx)

    def _service(self, service_id: str, *, start: bool) -> Result:
        """One service (the database or an add-on) started or stopped; the others are left as they are."""
        verb = "Starting" if start else "Stopping"
        for service in services_app.service_ids(self.ctx):
            if service.id == service_id:
                self.ctx.ui.working(f"{verb} {'the database' if service_id == 'database' else service_id}")
                (services_app.start if start else services_app.stop)(self.ctx, service)
                state = services_app.status_of(self.ctx, service)
                self.ctx.ui.ok(f"{'The database' if service_id == 'database' else service_id} is {state}")
                return Result(True, state)
        return Result(False, "unknown service", remedy="exakit status")
