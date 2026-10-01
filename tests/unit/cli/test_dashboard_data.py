"""The dashboard's facade reads what the commands answer, without printing, and names the actions as the ordinary commands."""

from __future__ import annotations

import unittest

from exakit.cli.dashboard_data import DashboardData
from tests.unit.app.harness import MANIFEST, Sandbox


class FacadeTest(unittest.TestCase):
    def test_a_fresh_machine_reads_as_not_installed_and_still_has_a_catalog_and_the_commands(self):
        box = Sandbox()
        try:
            data = DashboardData(box.ctx)
            status = data.status()
            self.assertFalse(status["installed"])
            self.assertIn("install", (status.get("remedy") or "").lower() + status["status"].lower())
            ids = {e["id"] for e in data.catalog()}
            self.assertTrue({"personal", "exapump", "dash-server", "json-tables"} <= ids)
            names = {c["command"] for c in data.commands()}
            self.assertTrue({"status", "ui", "marketplace", "update"} <= names)
            self.assertIn("exakit status", data.help_page("status"))
            self.assertEqual(box.out.getvalue(), "", "the facade prints nothing")
        finally:
            box.close()

    def test_an_installed_kit_reads_its_versions_and_marketplace(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            data = DashboardData(box.ctx)
            rows = {r["component"]: r for r in data.versions()}
            self.assertIn("personal", rows)
            entry = next(e for e in data.catalog() if e["id"] == "dash-server")
            self.assertTrue(entry["addon"])
            self.assertTrue(entry["tagline"])
            market = {r["id"]: r for r in data.marketplace()}
            self.assertIn("dash-server", market)
            self.assertIn(market["dash-server"]["status"], ("available", "installed", "not available on this machine", "already on this system"))
            for kind in ("marketplace", "update", "start", "stop"):
                self.assertTrue(callable(data.job(kind, "dash-server")))
        finally:
            box.close()
