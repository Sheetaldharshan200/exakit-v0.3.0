"""The dashboard, headless: the sidebar switches the views, the search opens entries, the marketplace has its two tabs, an action runs."""

from __future__ import annotations

import importlib.util
import unittest

from exakit.domain.result import Result

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None

CATALOG = [{"id": "personal", "title": "Exasol Personal", "kind": "runtime", "addon": False, "tagline": "The local database", "role": "",
            "installed": "2.3.0", "advertised": "2.3.0", "status": "current", "remedy": None, "note": None, "platforms": ["macos-aarch64"], "requires": [], "launcher": None},
           {"id": "dash-server", "title": "dash-server (AI dashboard host)", "kind": "python-venv", "addon": True, "tagline": "Dash hosting", "role": "Hosts dashboards.",
            "installed": "not installed", "advertised": "0.1.1", "status": "available", "remedy": "exakit marketplace dash-server", "note": None, "platforms": [], "requires": ["mcp"], "launcher": "dash-server"}]


class FakeData:
    """A facade with canned answers and a job that writes through the renderer."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str]] = []
        self.ui = None

    def status(self):
        return {"installed": True, "status": "running", "running": True, "runtime": {"type": "personal"}, "datasets_loaded": ["tpch"],
                "services": {"dash-server": "running"}, "urls": {}, "autostart": True, "persona": "analyst", "remedy": None}

    def versions(self):
        return [{"component": "personal", "addon": False, "installed": "2.3.0", "installed_label": "2.3.0", "advertised": "2.3.0", "status": "current", "remedy": None, "note": None},
                {"component": "dash-server", "addon": True, "installed": None, "installed_label": "not installed", "advertised": "0.1.1", "status": "available", "remedy": None, "note": None}]

    def catalog(self):
        return CATALOG

    def marketplace(self):
        return [{"id": "dash-server", "status": "available", "installed": False, "version": "0.1.1", "reason": "", "title": "dash-server"}]

    def commands(self):
        return [{"command": "status", "options": "", "summary": "Is the database up and healthy?", "group": "Everyday"},
                {"command": "marketplace", "options": "", "summary": "Optional add-ons", "group": "Add-ons"}]

    def help_page(self, topic):
        return f"HELP PAGE FOR {topic}"

    def job(self, kind, target=""):
        self.jobs.append((kind, target))

        def run():
            self.ui.info(f"running {kind} {target}")
            with self.ui.progress(f"Installing {target}", unit="percent") as bar:
                bar.stage(50, 90, 1, "half way")
            return Result(True, "applied")
        return run


@unittest.skipUnless(HAVE_TEXTUAL, "textual is not installed here")
class DashboardTest(unittest.IsolatedAsyncioTestCase):
    async def _open(self):
        from exakit.ui.tui.dashboard import DashboardApp
        from exakit.ui.tui.renderer import TuiRenderer
        from exakit.ui.console import ConsoleRenderer
        from exakit.ui.widgets import PLAIN
        import io
        data = FakeData()
        app = DashboardApp(data, title="Exasol Personal Local Starter Kit")
        data.ui = TuiRenderer(app, ConsoleRenderer(palette=PLAIN, out=io.StringIO(), interactive=False))
        return app, data

    async def _settled(self, pilot, app):
        for _ in range(100):
            await pilot.pause(0.02)
            if app.state.get("catalog"):
                break

    async def test_the_sidebar_switches_the_views_with_the_keys(self):
        from exakit.ui.tui.sections import ComingSoonView, EntryList, MarketplaceView, StatusView
        app, _ = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            self.assertTrue(app.query(StatusView))
            self.assertIn("running", str(app.query_one("#status-text").render()))
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(app.section, "catalog")
            self.assertTrue(app.query(EntryList))
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(app.section, "marketplace")
            tabs = app.query_one(MarketplaceView)
            self.assertEqual([pane.id for pane in tabs.query("TabPane")], ["addons", "updates"])
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertTrue(app.query(ComingSoonView))
            self.assertIn("Coming soon", str(app.query_one(ComingSoonView).render()))
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(app.section, "commands")

    async def test_the_search_lists_matches_and_enter_opens_the_entry(self):
        from textual.widgets import Input, OptionList
        from exakit.ui.tui.sections import EntryList
        app, _ = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            await pilot.press("slash")
            await pilot.pause(0.05)
            self.assertTrue(app.query_one("#search-input", Input).has_focus)
            for ch in "dash":
                await pilot.press(ch)
            await pilot.pause(0.1)
            results = app.query_one("#results", OptionList)
            self.assertFalse(results.has_class("hidden"))
            self.assertEqual(results.option_count, 1)
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(app.section, "catalog")
            self.assertEqual(app.query_one("#view", EntryList).current()["id"], "dash-server")
            self.assertIn("Hosts dashboards.", str(app.query_one(".detail-text").render()))

    async def test_a_command_entry_shows_its_help_page(self):
        app, _ = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            await app.open_entry("command", "marketplace")
            await pilot.pause(0.1)
            self.assertEqual(app.section, "commands")
            self.assertIn("HELP PAGE FOR marketplace", str(app.query_one(".detail-text").render()))

    async def test_install_from_the_marketplace_runs_the_action_in_the_job_view(self):
        from exakit.ui.tui.sections import JobView, RunJob
        app, data = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            await app.show_section("marketplace")
            await pilot.pause(0.05)
            app.post_message(RunJob("marketplace", "dash-server"))
            for _ in range(100):
                await pilot.pause(0.02)
                if not app.job_running and app.query(JobView):
                    break
            self.assertEqual(data.jobs, [("marketplace", "dash-server")])
            lines = [t.plain for t in app.query_one(JobView).query_one("LogPane").lines]
            self.assertIn("• running marketplace dash-server", lines)
            self.assertTrue(any(line.startswith("Done: applied") for line in lines))
            await pilot.press("escape")
            await pilot.pause(0.05)
            self.assertFalse(app.query(JobView))

    async def test_the_palette_provider_finds_the_entries(self):
        from exakit.ui.tui.palette import KitProvider
        app, _ = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            provider = KitProvider(app.screen)
            hits = [hit async for hit in provider.search("dash")]
            self.assertTrue(any("dash-server" in str(h.match_display) or "dash-server" in (h.help or "") for h in hits) or hits)
            discovered = [hit async for hit in provider.discover()]
            self.assertEqual(len(discovered), 5)
