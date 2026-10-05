import json
import unittest

from exakit.adapters.process.runner import Completed
from exakit.app.bridge import mcp
from exakit.domain.errors import BadInput, Failed, NotRunning
from tests.unit.app.harness import MANIFEST, Sandbox
from tests.unit.fakes import FakeClientOps, FakeExapump, FakeRuntime

OK = Completed(0, "ok", "")


def _readonly_rules(present_user=True, write_probe_ok=False):
    return [
        ("EXA_DBA_USERS", Completed(0, "EXAKIT_MCP_USER_PRESENT" if present_user else "EXAKIT_MCP_USER_MISSING", "")),
        ("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")),
        ("CURRENT_USER", Completed(0, "MCP_READONLY", "")),
        ("EXAKIT_MCP_READONLY_OK", Completed(0, "EXAKIT_MCP_READONLY_OK", "")),
        ("PRIVILEGE='CREATE SESSION'", Completed(0, "EXAKIT_CREATE_SESSION_OK", "")),
        ("PRIVILEGE='USE ANY SCHEMA'", Completed(0, "EXAKIT_USE_ANY_SCHEMA_OK", "")),
        ("PRIVILEGE='SELECT ANY TABLE'", Completed(0, "EXAKIT_SELECT_ANY_TABLE_OK", "")),
        ("PRIVILEGE NOT IN", Completed(0, "EXAKIT_SYS_PRIV_SCOPE_OK", "")),
        ("GRANTED_ROLE", Completed(0, "EXAKIT_ROLE_SCOPE_OK", "")),
        ("PRIVILEGE <> 'SELECT'", Completed(0, "EXAKIT_OBJ_PRIV_SCOPE_OK", "")),
        ("EXAKIT_MCP_PERMISSION_PROBE (ID", Completed(0 if write_probe_ok else 1, "", "insufficient privileges")),
    ]


def _box(**kw) -> Sandbox:
    manifest = {**MANIFEST}
    box = Sandbox(manifest=manifest, **kw)
    box.ctx.credentials = None
    from exakit.app.db.runtime_ops import credentials
    store = credentials(box.ctx)
    store.store("personal_sys_password", "adminpw")
    box.ctx.manifest_store.update(lambda m: m.set("runtime.password_file", str(store.path("personal_sys_password"))))
    box.ctx.runtime = FakeRuntime()
    return box


class ReadonlyUserTest(unittest.TestCase):
    def test_provisions_grants_validates_and_records(self):
        box = _box()
        try:
            pump = FakeExapump(_readonly_rules(present_user=False))
            box.ctx.exapump = pump
            mcp.configure_readonly_access(box.ctx)
            statements = [t for _, t in pump.calls]
            self.assertTrue(any(t.startswith("CREATE USER MCP_READONLY") for t in statements))
            self.assertTrue(any(t.startswith("ALTER USER MCP_READONLY") for t in statements))
            self.assertTrue(any("GRANT SELECT ANY TABLE" in t for t in statements))
            self.assertTrue(any("EXAKIT_MCP_PERMISSION_PROBE" in t for t in statements))
            m = box.manifest()
            self.assertEqual(m.get("components.mcp_server.connection.user"), "mcp_readonly")
            self.assertEqual(m.get("components.mcp_server.connection.schemas"), ["STARTER_KIT"])
            self.assertTrue(m.get("components.mcp_server.connection.validated"))
            self.assertTrue(box.ctx.credentials.exists("mcp_readonly_password"))
            self.assertNotIn("adminpw", box.screen())
        finally:
            box.close()

    def test_a_writable_readonly_user_stops_setup(self):
        box = _box()
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules(write_probe_ok=True))
            with self.assertRaises(Failed) as ctx:
                mcp.configure_readonly_access(box.ctx)
            self.assertIn("Security check failed", str(ctx.exception))
        finally:
            box.close()

    def test_missing_exapump_or_password(self):
        box = _box()
        try:
            box.ctx.exapump = None
            box.ctx.runner.which_table = {}
            with self.assertRaises(Failed):
                mcp.configure_readonly_access(box.ctx)
        finally:
            box.close()


class SetupTest(unittest.TestCase):
    def test_env_selection_all_narrows_to_detected(self):
        box = _box(env={"EXAKIT_MCP_CLIENTS": "all"})
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules())
            box.ctx.clients = FakeClientOps(docs={
                "discover": {"clients": [{"id": "claude_code", "detected": True, "configured": False}, {"id": "cursor", "detected": False}]},
                "setup": {"status": "success_with_warnings", "details": {"configured_clients": ["claude_code"], "skipped_clients": []}, "findings": []},
            })
            result = mcp.setup(box.ctx)
            self.assertEqual(result.status, "configured")
            self.assertEqual(box.ctx.clients.calls[-1], ("setup", ("claude_code",)))
            self.assertIn("MCP configured for Claude Code\n", box.screen())
            self.assertIn("skipped: claude_desktop,cursor", box.screen())
        finally:
            box.close()

    def test_skip_word_and_invalid_value(self):
        box = _box(env={"EXAKIT_MCP_CLIENTS": "skip"})
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules())
            self.assertEqual(mcp.setup(box.ctx).status, "skipped")
            box.env["EXAKIT_MCP_CLIENTS"] = "notepad"
            with self.assertRaises(BadInput):
                mcp.setup(box.ctx)
        finally:
            box.close()

    def test_non_interactive_menu_takes_pending_defaults(self):
        box = _box()
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules())
            box.ctx.clients = FakeClientOps(docs={
                "discover": {"clients": [{"id": "codex", "detected": True, "configured": False}, {"id": "cursor", "detected": True, "configured": True}]},
                "setup": {"status": "success", "details": {"configured_clients": ["codex"], "skipped_clients": []}},
            })
            mcp.setup(box.ctx)
            self.assertEqual(box.ctx.clients.calls[-1], ("setup", ("codex",)))
        finally:
            box.close()

    def test_nothing_pending_says_so(self):
        box = _box()
        try:
            box.ctx.clients = FakeClientOps(docs={"discover": {"clients": [{"id": "cursor", "detected": True, "configured": True}]}})
            self.assertEqual(mcp.setup(box.ctx).status, "skipped")
            self.assertIn("already connected", box.screen())
        finally:
            box.close()

    def test_setup_failure_is_a_failed_error(self):
        box = _box(env={"EXAKIT_MCP_CLIENTS": "codex"})
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules())
            box.ctx.clients = FakeClientOps(docs={"setup": {"status": "blocked", "details": {"configured_clients": []}}}, codes={"setup": 1})
            with self.assertRaises(Failed):
                mcp.setup(box.ctx)
        finally:
            box.close()


class StatusDoctorRemoveTest(unittest.TestCase):
    def test_status_json_is_stamped(self):
        box = _box(json_mode=True)
        try:
            box.ctx.clients = FakeClientOps(docs={"status": {"operation": "status", "status": "success", "details": {"clients": [
                {"client": "cursor", "state": "configured", "path": "/x/.cursor/mcp.json"}]},
                "findings": [{"severity": "warning", "code": "permission_drift", "recommended_action": "Run: exakit mcp-doctor", "scope": None}]}})
            result = mcp.status(box.ctx, [])
            doc = json.loads(result.to_json())
            self.assertTrue(doc["installed"])
            self.assertEqual(doc["remedy"], "Run: exakit mcp-doctor")
            self.assertEqual(doc["details"]["clients"][0]["client"], "cursor")
        finally:
            box.close()

    def test_status_human_panel(self):
        box = _box()
        try:
            box.ctx.clients = FakeClientOps(docs={"status": {"operation": "status", "status": "success", "details": {"clients": [
                {"client": "cursor", "state": "configured", "path": box.env["HOME"] + "/.cursor/mcp.json"},
                {"client": "codex", "state": "not_set_up", "path": None}]}, "findings": []}})
            mcp.status(box.ctx, ["cursor"])
            screen = box.screen()
            self.assertIn("Cursor", screen)
            self.assertIn("~/.cursor/mcp.json", screen)
            self.assertNotIn("not_set_up", screen)
        finally:
            box.close()

    def test_doctor_refuses_without_a_running_database(self):
        box = _box(json_mode=True)
        try:
            box.ctx.runtime = FakeRuntime(state="stopped")
            with self.assertRaises(NotRunning) as ctx:
                mcp.doctor(box.ctx, [])
            self.assertEqual(ctx.exception.remedy, "exakit start")
            self.assertEqual(ctx.exception.data["status"], "stopped")
        finally:
            box.close()

    def test_doctor_repairs_drift_once(self):
        box = _box()
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules())
            drift = {"operation": "doctor", "status": "success_with_warnings", "summary": "x", "details": {"clients": []},
                     "findings": [{"severity": "warning", "code": "permission_drift", "message": "mode", "recommended_action": "Run: exakit mcp-doctor"}]}
            box.ctx.clients = FakeClientOps(docs={"doctor": drift, "repair": {"status": "success"}})
            mcp.doctor(box.ctx, [])
            ops = [c[0] for c in box.ctx.clients.calls]
            self.assertEqual(ops, ["doctor", "repair", "doctor"])
        finally:
            box.close()

    def test_remove_requires_names(self):
        box = _box()
        try:
            with self.assertRaises(BadInput):
                mcp.remove(box.ctx, [])
            with self.assertRaises(BadInput):
                mcp.remove(box.ctx, ["all"])
            box.ctx.clients = FakeClientOps(docs={"uninstall": {"operation": "uninstall", "status": "success", "changes": [{"kind": "remove", "path": "/x"}]}})
            mcp.remove(box.ctx, ["claude"])
            self.assertEqual(box.ctx.clients.calls[-1], ("uninstall", ("claude_desktop", "claude_code"), ()))
        finally:
            box.close()

    def test_register_addon_servers_and_pins(self):
        box = _box()
        try:
            box.ctx.exapump = FakeExapump(_readonly_rules())
            box.ctx.clients = FakeClientOps(docs={
                "status": {"artifacts": [{"client": "cursor"}]},
                "register": {"dash_server": {"configured_clients": ["cursor"]}},
                "setup": {"status": "success", "details": {"configured_clients": ["cursor"]}}})
            self.assertTrue(mcp.register_addon_servers(box.ctx, "dash-server"))
            self.assertTrue(mcp.refresh_client_pins(box.ctx, "2.3.0"))
            self.assertIn("exasol-mcp-server@2.3.0", box.screen())
        finally:
            box.close()


if __name__ == "__main__":
    unittest.main()


class ClaudeTogetherTest(unittest.TestCase):
    """"Claude" is the desktop app and Claude Code: one menu row, one name, one status row."""

    def _states(self, box, **states):
        rows = [{"id": cid, "detected": state != "missing", "configured": state == "connected"} for cid, state in states.items()]
        box.ctx.clients = FakeClientOps(docs={"discover": {"clients": rows}})

    def test_one_claude_row_configures_both_apps(self):
        box = _box()
        try:
            self._states(box, claude_desktop="pending", claude_code="pending", codex="pending")
            self.assertEqual(mcp._select_from_menu(box.ctx), ["claude_desktop", "claude_code", "codex"])
        finally:
            box.close()

    def test_the_claude_row_says_which_app_it_still_connects(self):
        from exakit.app.bridge.mcp_clients import _group_row
        row = _group_row("claude", ("claude_desktop", "claude_code"), {"claude_desktop": "connected", "claude_code": "pending"})
        self.assertEqual((row.label, row.hint, row.disabled), ("Claude", "Claude Code (desktop app already connected)", False))
        both = _group_row("claude", ("claude_desktop", "claude_code"), {"claude_desktop": "pending", "claude_code": "pending"})
        self.assertEqual(both.hint, "desktop app and Claude Code")
        none = _group_row("claude", ("claude_desktop", "claude_code"), {"claude_desktop": "missing", "claude_code": "missing"})
        self.assertEqual((none.hint, none.disabled), ("not installed", True))
        box = _box()
        try:
            self._states(box, claude_desktop="connected", claude_code="pending")
            self.assertEqual(mcp._select_from_menu(box.ctx), ["claude_code"], "only the app still waiting is configured")
        finally:
            box.close()

    def test_the_names_put_both_apps_under_claude(self):
        from exakit.app.bridge.mcp_clients import client_names
        self.assertEqual(client_names(["claude_desktop", "claude_code", "cursor"]), ["Claude (desktop app and Claude Code)", "Cursor"])
        self.assertEqual(client_names(["claude_code"]), ["Claude Code"])


class RestartNeededTest(unittest.TestCase):
    """An app that read its config before the kit changed it has not loaded the server: the doctor and the setup say so."""

    def _doc(self, path):
        return {"status": "success", "artifacts": [{"client": "claude_desktop", "path": str(path), "removed_at": None}]}

    def test_claude_desktop_open_since_before_the_change_must_be_reopened(self):
        import os
        import tempfile
        import time
        from pathlib import Path
        from exakit.app.bridge.mcp_clients import _mark_restart, restart_needed
        from exakit.domain.platform import Platform
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "claude_desktop_config.json"
            config.write_text("{}")
            changed = time.time()
            os.utime(config, (changed, changed))
            before = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(changed - 120))
            after = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(changed + 120))
            ps = ("ps", "-axo", "lstart=,comm=")
            for started, expected in ((before, ["claude_desktop"]), (after, [])):
                box = _box(platform=Platform("macos", "aarch64"))
                try:
                    box.runner.responses[ps] = Completed(0, f"{started} /Applications/Claude.app/Contents/MacOS/Claude\n", "")
                    self.assertEqual(restart_needed(box.ctx, self._doc(config)), expected)
                    doc = self._doc(config)
                    _mark_restart(box.ctx, doc)
                    self.assertEqual(doc["status"], "success_with_warnings" if expected else "success")
                    self.assertEqual((doc.get("details") or {}).get("restart_needed"), expected or None)
                finally:
                    box.close()
            box = _box(platform=Platform("linux", "x86_64"))
            try:
                self.assertEqual(restart_needed(box.ctx, self._doc(config)), [], "an OS that cannot say asks for nothing")
            finally:
                box.close()

    def test_the_start_time_is_read_on_macos_and_windows(self):
        from exakit.adapters.process.apps import started_at
        from tests.unit.fakes import FakeRunner
        mac = FakeRunner(responses={("ps", "-axo", "lstart=,comm="): Completed(0, "Mon Oct  5 11:39:30 2026 /Applications/Claude.app/Contents/MacOS/Claude\n"
                                                                             "Mon Oct  5 11:39:31 2026 /Applications/Claude.app/Contents/Frameworks/Helper\n", "")})
        self.assertIsNotNone(started_at(mac, "macos", "claude_desktop"))
        win = FakeRunner(responses={("powershell",): Completed(0, "2026-10-05T06:09:30.0000000Z\n", "")})
        self.assertEqual(started_at(win, "windows", "claude_desktop"), 1791180570.0)
        self.assertIsNone(started_at(FakeRunner(), "macos", "claude_desktop"), "not running")

