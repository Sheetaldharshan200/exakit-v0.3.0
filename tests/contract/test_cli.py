"""The frozen contracts, checked against the real CLI in a sandbox.

Every ``--json`` answer is one object on stdout and nothing else; every
state query carries installed, status and remedy; refusals exit 2 with the
refusal object; no install exits 4. The migrated set and the legacy set
cover every command exactly once. Where the legacy CLI is runnable (bash on
the machine), the document surfaces (catalog, help) must agree with it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = {
    "manifest_version": 1, "kit_level": 1, "installed_at": "2026-09-30T00:00:00Z", "os": "macos", "arch": "arm64",
    "runtime": {"type": "personal", "status": "running", "version": "2.3.0"},
    "components": {"skills": {"version": "1.12.1"}, "mcp_server": {"version": "2.2.0"}},
    "data": {"loaded": True, "datasets": {"tpch": {"loaded": True}}},
    "steps_completed": ["launcher", "runtime", "exapump", "mcp", "pyexasol", "exakit_helper"], "log_dir": "/tmp/x",
}


class Sandbox:
    def __init__(self, *, manifest: dict | None) -> None:
        self.dir = tempfile.mkdtemp(prefix="exakit-contract-")
        self.home = Path(self.dir) / "home"
        self.home.mkdir()
        if manifest is not None:
            (self.home / "manifest.json").write_text(json.dumps(manifest))
        self.env = {**os.environ, "EXAKIT_HOME": str(self.home), "EXAKIT_BIN_DIR": str(Path(self.dir) / "bin"),
                    "EXAKIT_VERSIONS_TTL": "999999", "EXAKIT_NO_UPDATE_NOTICE": "1", "NO_COLOR": "1",
                    "PYTHONPATH": str(REPO)}

    def run(self, *args: str, legacy: bool = False) -> subprocess.CompletedProcess:
        cmd = ["bash", str(REPO / "setup" / "legacy-exakit"), *args] if legacy else [sys.executable, "-m", "exakit", *args]
        return subprocess.run(cmd, cwd=REPO, env=self.env, capture_output=True, text=True, timeout=120)

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def _one_object(text: str) -> dict:
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 1, f"expected one JSON line, got {len(lines)}: {text[:200]!r}"
    return json.loads(lines[0])


class StateQueryShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(manifest=MANIFEST)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def test_persona_list_json(self):
        done = self.box.run("persona", "list", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = _one_object(done.stdout)
        self.assertEqual([k for k in doc][:3], ["installed", "status", "remedy"])
        self.assertEqual((doc["installed"], doc["status"], doc["remedy"], doc["recorded"]), (True, "none", None, None))
        self.assertEqual([p["id"] for p in doc["personas"]], ["analyst", "data-engineer", "data-scientist", "minimal"])
        self.assertEqual(set(doc["personas"][0]), {"id", "title", "summary", "source", "recorded"})

    def test_persona_plan_json_shape(self):
        done = self.box.run("persona", "plan", "data-scientist", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = _one_object(done.stdout)
        for key in ("installed", "status", "remedy", "persona", "datasets", "mcp_clients", "addons", "skills", "pending", "failed"):
            self.assertIn(key, doc)
        self.assertEqual(doc["persona"], {"id": "data-scientist", "title": "Data Scientist", "source": "kit"})
        self.assertEqual(doc["datasets"][0], {"id": "tpch", "state": "done"})
        self.assertEqual({d["id"] for d in doc["datasets"]}, {"tpch", "energy", "weather"})
        self.assertIn(doc["status"], ("pending", "complete"))
        if doc["status"] == "pending":
            self.assertEqual(doc["remedy"], "exakit persona apply data-scientist --yes")
        self.assertTrue(all(s["state"] in ("done", "pending", "skipped") for s in doc["addons"]))

    def test_persona_show_json_is_the_document(self):
        doc = _one_object(self.box.run("persona", "show", "minimal", "--json").stdout)
        self.assertEqual(doc["id"], "minimal")
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["source"], "kit")
        self.assertNotIn("installed", doc)

    def test_recorded_persona_is_marked(self):
        box = Sandbox(manifest={**MANIFEST, "persona": {"id": "analyst", "source": "install"}})
        try:
            doc = _one_object(box.run("persona", "list", "--json").stdout)
            self.assertEqual((doc["status"], doc["recorded"]), ("recorded", "analyst"))
            self.assertTrue([p for p in doc["personas"] if p["id"] == "analyst"][0]["recorded"])
        finally:
            box.close()

    def test_version_json_shape(self):
        done = self.box.run("version", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = _one_object(done.stdout)
        self.assertEqual([k for k in doc][:3], ["installed", "status", "remedy"])
        self.assertIn(doc["status"], ("current", "update_pending"))
        self.assertEqual(set(doc) - {"installed", "status", "remedy"}, {"pending", "kit", "versions_source", "components"})
        row = doc["components"][0]
        self.assertEqual(set(row), {"component", "addon", "installed", "installed_label", "advertised", "status",
                                    "remedy", "severity", "note", "platform_note"})
        self.assertEqual(row["component"], "exakit")
        statuses = {"current", "ahead", "unsupported", "unknown", "available", "blocked_on_kit", "missing", "update_available"}
        self.assertTrue(all(r["status"] in statuses for r in doc["components"]))

    def test_whats_new_json(self):
        doc = _one_object(self.box.run("whats-new", "0.3.0", "--json").stdout)
        self.assertEqual(doc["version"], "0.3.0")
        self.assertTrue(doc["notes"])


class RefusalsAndCodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(manifest=MANIFEST)
        cls.empty = Sandbox(manifest=None)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()
        cls.empty.close()

    def test_unknown_persona_is_a_refusal_naming_the_known_ones(self):
        done = self.box.run("persona", "show", "nope", "--json")
        self.assertEqual(done.returncode, 2)
        doc = _one_object(done.stdout)
        self.assertEqual((doc["ok"], doc["rejected"], doc["remedy"]), (False, True, None))
        self.assertIn("analyst", doc["error"])

    def test_bad_option_and_bad_subcommand(self):
        self.assertEqual(self.box.run("version", "--nope").returncode, 2)
        self.assertEqual(self.box.run("persona", "bogus").returncode, 2)
        self.assertEqual(self.box.run("persona", "list", "--yes").returncode, 2)
        self.assertEqual(self.box.run("persona", "show").returncode, 2)

    def test_not_installed_exits_4_with_the_state_shape(self):
        done = self.empty.run("version", "--json")
        self.assertEqual(done.returncode, 4)
        doc = _one_object(done.stdout)
        self.assertEqual((doc["ok"], doc["rejected"]), (False, False))
        self.assertIn("remedy", doc)

    def test_human_refusal_goes_to_stderr_with_nothing_on_stdout(self):
        done = self.box.run("persona", "show", "nope")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("Unknown persona", done.stderr)

    def test_help_topic_and_component_pages(self):
        self.assertEqual(self.box.run("mcp").returncode, 0)
        self.assertIn("MCP server", self.box.run("mcp").stdout)
        self.assertIn("persona", self.box.run("persona", "--help").stdout)
        self.assertEqual(self.box.run("help", "--json").returncode, 0)


class PhaseBShapeTest(unittest.TestCase):
    """marketplace --list, uninstall <addon>, persona apply: the shapes and exit codes agents branch on."""

    @classmethod
    def setUpClass(cls):
        doc = {**MANIFEST, "components": {**MANIFEST["components"], "dash_server": {"version": "0.1.1", "port": 5100}}}
        cls.box = Sandbox(manifest=doc)
        bin_dir = Path(cls.box.env["EXAKIT_BIN_DIR"])
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "dash-server").write_text("#!/bin/sh\n")
        cls.box.env["EXAKIT_MCP_CLIENTS"] = "skip"

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def test_marketplace_list_json_is_the_legacy_document(self):
        done = self.box.run("marketplace", "--list", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = _one_object(done.stdout)
        self.assertEqual(list(doc), ["addons"])
        rows = {r["id"]: r for r in doc["addons"]}
        self.assertEqual(set(rows), {"dash-server", "dbt-exasol", "exasol-scheduler", "exasol-vscode", "json-tables"})
        self.assertEqual(rows["dash-server"], {"id": "dash-server", "status": "installed", "installed": True, "version": "0.1.1"})
        for row in rows.values():
            self.assertIn(row["status"], ("installed", "available", "managed outside the kit", "not in this kit copy", "not available on this machine"))
            self.assertEqual(row["installed"], row["status"] == "installed")
        self.assertEqual(_one_object(self.box.run("marketplace", "--json").stdout), doc)

    def test_marketplace_without_a_terminal_installs_nothing(self):
        done = self.box.run("marketplace")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("nothing was installed", done.stdout)
        self.assertIn("marketplace --list", done.stdout)

    def test_marketplace_refusals(self):
        self.assertEqual(self.box.run("marketplace", "nope").returncode, 2)
        self.assertEqual(self.box.run("marketplace", "--list", "dash-server").returncode, 2)
        self.assertEqual(self.box.run("marketplace", "--frob").returncode, 2)

    def test_uninstall_one_addon_codes(self):
        self.assertEqual(self.box.run("uninstall", "nope").returncode, 2)
        self.assertEqual(self.box.run("uninstall", "dash-server", "json-tables").returncode, 2)
        not_installed = self.box.run("uninstall", "dbt-exasol")
        self.assertEqual(not_installed.returncode, 0, not_installed.stderr)
        self.assertIn("not installed", not_installed.stdout)
        declined = self.box.run("uninstall", "dash-server", "--json")
        self.assertEqual(declined.returncode, 5)
        doc = _one_object(declined.stdout)
        self.assertEqual((doc["ok"], doc["remedy"]), (False, "exakit uninstall dash-server --yes"))
        dry = self.box.run("uninstall", "dash-server", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("will remove", dry.stdout)
        self.assertTrue((Path(self.box.env["EXAKIT_BIN_DIR"]) / "dash-server").exists())

    def test_persona_apply_refuses_without_yes_and_records_nothing(self):
        box = Sandbox(manifest={**MANIFEST, "components": {**MANIFEST["components"], "skills": {"version": "0.0.1"}}})
        box.env["EXAKIT_MCP_CLIENTS"] = "skip"
        box.env["EXAKIT_MARKETPLACE_ADDONS"] = "none"
        try:
            done = box.run("persona", "apply", "minimal", "--json")
            self.assertEqual(done.returncode, 5, done.stdout)
            doc = _one_object(done.stdout)
            self.assertEqual((doc["ok"], doc["remedy"]), (False, "exakit persona apply minimal --yes"))
            self.assertEqual(doc["skills"], [{"id": "skills", "state": "pending"}])
            self.assertNotIn("persona", json.loads((box.home / "manifest.json").read_text()))
        finally:
            box.close()

    def test_persona_apply_complete_records_the_persona(self):
        box = Sandbox(manifest=MANIFEST)
        box.env["EXAKIT_MCP_CLIENTS"] = "skip"
        box.env["EXAKIT_MARKETPLACE_ADDONS"] = "none"
        try:
            done = box.run("persona", "apply", "minimal", "--yes", "--json")
            self.assertEqual(done.returncode, 0, done.stdout)
            doc = _one_object(done.stdout)
            self.assertEqual((doc["installed"], doc["status"], doc["remedy"], doc["pending"]), (True, "complete", None, 0))
            recorded = json.loads((box.home / "manifest.json").read_text())["persona"]
            self.assertEqual((recorded["id"], recorded["source"]), ("minimal", "apply"))
            self.assertEqual(_one_object(box.run("persona", "list", "--json").stdout)["recorded"], "minimal")
        finally:
            box.close()


class StateQueryPhaseCTest(unittest.TestCase):
    """status and info: the tri-state exit code and the keys AGENTS.md promises, against the real CLI."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(manifest=MANIFEST)
        cls.box.env["EXAKIT_PERSONAL_DEPLOY_DIR"] = str(Path(cls.box.dir) / "no-deployment")
        cls.box.env["PATH"] = str(Path(cls.box.dir) / "empty-path")
        cls.empty = Sandbox(manifest=None)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()
        cls.empty.close()

    def test_status_json_keys_and_exit_3_without_a_database(self):
        done = self.box.run("status", "--json")
        self.assertEqual(done.returncode, 3, done.stderr)
        doc = _one_object(done.stdout)
        self.assertEqual(list(doc)[:3], ["installed", "status", "remedy"])
        self.assertTrue(doc["installed"])
        self.assertIn(doc["status"], ("not deployed", "no database", "stopped"))
        for key in ("installing", "install_step", "runtime", "platform", "wsl_version", "running", "services", "urls", "autostart",
                    "datasets_loaded", "datasets_source", "steps_completed", "steps_missing", "remedies", "remedy_hints",
                    "last_failure", "last_failure_at", "manifest", "persona", "schema_version"):
            self.assertIn(key, doc, key)
        self.assertFalse(doc["running"])
        self.assertEqual(doc["remedy"], doc["remedies"]["database"])
        self.assertEqual(doc["datasets_loaded"], ["tpch"])

    def test_status_human_screen_exit_3(self):
        done = self.box.run("status")
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("Kit", done.stdout)
        self.assertIn("Data", done.stdout)

    def test_info_json_is_the_record_with_the_state_keys(self):
        done = self.box.run("info", "--json")
        self.assertEqual(done.returncode, 3, done.stderr)
        doc = _one_object(done.stdout)
        self.assertEqual(list(doc)[:3], ["installed", "status", "remedy"])
        self.assertEqual(doc["runtime"]["type"], "personal")
        self.assertEqual(set(doc["skills"]), {"installed_version", "advertised_version", "status", "next"})

    def test_not_installed_state_queries_exit_4_with_installed_false(self):
        for command in (("status", "--json"), ("info", "--json"), ("version", "--json")):
            done = self.empty.run(*command)
            self.assertEqual(done.returncode, 4, command)
            doc = _one_object(done.stdout)
            self.assertEqual((doc["installed"], doc["status"]), (False, "not installed"), command)
            self.assertTrue(doc["remedy"])
        self.assertEqual(self.empty.run("status").returncode, 4)
        self.assertEqual(self.empty.run("status").stdout, "")

    def test_bad_options(self):
        self.assertEqual(self.box.run("status", "--nope").returncode, 2)
        self.assertEqual(self.box.run("autostart", "on").returncode, 2)
        self.assertEqual(self.box.run("start", "--nope").returncode, 2)


class MigrationSplitTest(unittest.TestCase):
    def test_every_command_is_in_exactly_one_world(self):
        from exakit.cli.main import MIGRATED_COMMANDS, _LEGACY_WORDS
        self.assertEqual(MIGRATED_COMMANDS & _LEGACY_WORDS, set())
        docs = json.loads((REPO / "setup" / "help" / "exakit.json").read_text())
        documented = {c["command"].split()[0] for c in docs["commands"]}
        self.assertEqual(documented - MIGRATED_COMMANDS - _LEGACY_WORDS, set())

    def test_launcher_copies_are_byte_identical(self):
        self.assertEqual((REPO / "setup" / "exakit").read_bytes(), (REPO / "bootstrap" / "exakit").read_bytes())
        self.assertEqual((REPO / "setup" / "exakit.ps1").read_bytes(), (REPO / "bootstrap" / "exakit.ps1").read_bytes())


@unittest.skipUnless(shutil.which("bash"), "bash is needed to run the legacy CLI")
class LegacyAgreementTest(unittest.TestCase):
    """The document surfaces must say the same thing whichever CLI answers."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(manifest=MANIFEST)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def _legacy_json(self, *args: str) -> dict | None:
        done = self.box.run(*args, legacy=True)
        if done.returncode != 0 or not done.stdout.strip():
            return None
        try:
            return json.loads(done.stdout)
        except ValueError:
            return None

    def test_catalog_json_agrees(self):
        legacy = self._legacy_json("catalog", "--json")
        if legacy is None:
            self.skipTest("the legacy catalog needs a Python the shell can find")
        new = _one_object(self.box.run("catalog", "--json").stdout)
        self.assertEqual(new["count"], legacy["count"])
        self.assertEqual([r["invocation"] for r in new["commands"]], [r["invocation"] for r in legacy["commands"]])
        self.assertEqual(set(new["documents"]), set(legacy["documents"]))

    def test_help_json_agrees(self):
        legacy = self._legacy_json("help", "--json")
        if legacy is None:
            self.skipTest("the legacy help needs a Python the shell can find")
        new = _one_object(self.box.run("help", "--json").stdout)
        self.assertEqual(new, legacy)


if __name__ == "__main__":
    unittest.main()
