"""The dashboard, headless: the sidebar switches the views, the search opens entries, the marketplace has its two tabs, an action runs."""

from __future__ import annotations

import importlib.util
import time
import unittest
from pathlib import Path

from exakit.domain.result import Result

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None

CATALOG = [{"id": "personal", "title": "Exasol Personal", "kind": "runtime", "addon": False, "tagline": "The local database", "role": "",
            "installed": "2.3.0", "advertised": "2.3.0", "status": "current", "remedy": None, "note": None, "platforms": ["macos-aarch64"], "requires": [], "launcher": None},
           {"id": "dash-server", "title": "dash-server (AI dashboard host)", "kind": "python-venv", "addon": True, "tagline": "Dash hosting", "role": "Hosts dashboards.",
            "installed": "not installed", "advertised": "0.1.1", "status": "available", "remedy": "exakit marketplace dash-server", "note": None, "platforms": [], "requires": ["mcp"], "launcher": "dash-server",
            "market": "available", "market_reason": ""},
           {"id": "exasol-vscode", "title": "Exasol for VS Code", "kind": "host-extension", "addon": True, "tagline": "SQL in VS Code", "role": "",
            "installed": "not installed", "advertised": None, "status": "unknown", "remedy": None, "note": None, "platforms": [], "requires": ["personal"], "launcher": None,
            "market": "system", "market_reason": ""}]


class FakeData:
    """A facade with canned answers and a job that writes through the renderer."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str]] = []
        self.ui = None

    def status(self):
        return {"installed": True, "status": "running", "running": True, "runtime": {"type": "personal"}, "datasets_loaded": ["tpch"],
                "services": {"dash-server": "running", "exasol-scheduler": "stopped (gave up after 5 rapid failures)"}, "urls": {}, "autostart": True,
                "persona": "analyst", "remedy": None}

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

    def help_page(self, topic, width=100):
        return f"HELP PAGE FOR {topic}"

    def scheduler(self):
        return {"tasks": "3", "enabled": "2", "last_run": "2026-10-02 01:00", "last_status": "SUCCESS", "failures_24h": "1", "schema": "SCHED"}

    def info(self):
        return {"kit": {"version": "0.3.0", "source": "Sheetaldharshan200/exakit-v0.3.0@main"},
                "runtime": {"dsn": "127.0.0.1:8563", "user": "sys", "password_file": "/home/me/.exasol-starter-kit/credentials/sys_password"},
                "components": {"mcp_server": {"connection": {"user": "mcp_readonly", "password_file": "/home/me/.exasol-starter-kit/credentials/mcp"}}}}

    log_file = None

    def log_path(self):
        return self.log_file

    def job(self, kind, target=""):
        self.jobs.append((kind, target))

        def run():
            self.ui.info(f"running {kind} {target}")
            if self.log_file:
                with open(self.log_file, "a", encoding="utf-8") as handle:
                    handle.write("2026-10-02 00:00:01 CMD   exasol stop -> 0\n2026-10-02 00:00:02 INFO  shown through the renderer already\n")
            with self.ui.progress(f"Installing {target}", unit="percent") as bar:
                bar.stage(50, 90, 1, "half way")
                time.sleep(0.4)
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
        for _ in range(400):
            await pilot.pause(0.02)
            if app.state.get("catalog") and app.query("#view"):
                break

    async def test_the_sidebar_switches_the_views_with_the_keys(self):
        from exakit.ui.tui.sections import ComingSoonView, EntryList, MarketplaceView, StatusView
        app, _ = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            self.assertTrue(app.query(StatusView))
            from exakit.ui.tui.sections import Card
            cards = {c.title_text: c for c in app.query(Card)}
            self.assertIn("Starter kit", cards)
            self.assertIn("Sheetaldharshan200/exakit-v0.3.0@main", cards["Starter kit"].lines.plain)
            self.assertIn("Exasol Personal", cards)
            self.assertEqual(cards["Exasol Personal"].actions, [("Stop", "service-stop", "database")])
            self.assertIn("127.0.0.1:8563", cards["Exasol Personal"].lines.plain)
            self.assertIn("~/.exasol-starter-kit/credentials/sys_password" if str(Path.home()) == "/home/me" else "credentials/sys_password", cards["Exasol Personal"].lines.plain)
            heights = {c.styles.height.value for c in app.query(Card) if c.styles.height is not None}
            self.assertEqual(len(heights), 1, "every card has the same height")
            self.assertIn("dash-server (AI dashboard host)", cards)
            self.assertEqual(cards["dash-server (AI dashboard host)"].actions, [("Stop", "service-stop", "dash-server")])
            self.assertIn("Sample data", cards)
            self.assertIn("Autostart", cards)
            scheduler = cards["exasol-scheduler"]
            self.assertIn("3 (2 enabled)", scheduler.lines.plain)
            self.assertIn("2026-10-02 01:00  SUCCESS", scheduler.lines.plain)
            self.assertEqual(scheduler.actions, [("Start", "service-start", "exasol-scheduler"), ("Repair", "update", "exasol-scheduler")])
            from textual.widgets import Button
            top = {str(b.label): b for b in app.query("#actions Button")}
            self.assertEqual(top["Start everything"].variant, "success", "the scheduler is stopped: Start is green")
            self.assertEqual(top["Stop everything"].variant, "error", "Stop is always red")
            self.assertEqual(cards["Exasol Personal"].query_one(Button).variant, "error")
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(app.section, "catalog")
            self.assertTrue(app.query(EntryList))
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(app.section, "marketplace")
            tabs = app.query_one(MarketplaceView)
            self.assertEqual([pane.id for pane in tabs.query("TabPane")], ["addons", "updates"])
            from textual.widgets import Button
            everything = [b for b in tabs.query(Button) if str(b.label) == "Update everything"]
            self.assertEqual(len(everything), 1, "one Update everything, in the header")
            self.assertEqual([str(b.label) for b in tabs.query("#updates-list Button")], ["Update this one"])
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertTrue(app.query(ComingSoonView))
            self.assertIn("Coming soon", app.query_one(ComingSoonView).facts.plain)
            await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(app.section, "commands")

    async def test_the_search_lists_matches_and_enter_opens_the_entry(self):
        from textual.widgets import Input
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
            from exakit.ui.tui.choices import ChoiceList
            results = app.query_one("#results", ChoiceList)
            self.assertFalse(results.has_class("hidden"))
            self.assertEqual([o.id for o in results.options], ["item:dash-server"])
            await pilot.press("tab")
            await pilot.pause(0.05)
            self.assertEqual(app.query_one("#search-input", Input).value, "dash-server", "Tab completes the typed text")
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(app.section, "catalog")
            view = app.query_one("#view", EntryList)
            self.assertEqual(view.current()["id"], "dash-server")
            self.assertIn("Hosts dashboards.", view.detail_of(view.current()).plain)

    async def test_an_add_on_the_kit_did_not_install_is_said_so(self):
        from exakit.ui.tui.sections import catalog_detail
        self.assertIn("installed outside the kit, not managed by exakit", catalog_detail(CATALOG[2]).plain)
        self.assertIn("present (managed outside the kit)", catalog_detail(CATALOG[2]).plain)
        self.assertIn("install with: exakit marketplace dash-server", catalog_detail(CATALOG[1]).plain)
        unavailable = {**CATALOG[2], "market": "unavailable", "market_reason": "VS Code was not found"}
        self.assertIn("unavailable: VS Code was not found", catalog_detail(unavailable).plain)

    async def test_a_refresh_shows_a_loader_until_the_data_is_back(self):
        from exakit.ui.tui.dashboard import DashboardApp
        from exakit.ui.tui.panels import Loader

        class Slow(FakeData):
            def status(self):
                time.sleep(0.4)
                return super().status()

        app = DashboardApp(Slow(), title="t")
        async with app.run_test(size=(120, 40)) as pilot:
            seen = False
            for _ in range(60):
                await pilot.pause(0.02)
                if app.query_one(Loader).active:
                    seen = True
                    break
            self.assertTrue(seen, "the loader shows while the data loads")
            await self._settled(pilot, app)
            for _ in range(40):
                await pilot.pause(0.02)
                if not app.query_one(Loader).active:
                    break
            self.assertFalse(app.query_one(Loader).active, "and hides when it is back")

    async def test_a_command_entry_shows_its_help_page(self):
        app, _ = await self._open()
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            await app.open_entry("command", "marketplace")
            await pilot.pause(0.1)
            self.assertEqual(app.section, "commands")
            self.assertIn("HELP PAGE FOR marketplace", str(app.query_one(".detail-text").render()))

    async def test_install_from_the_marketplace_runs_the_action_in_the_job_view(self):
        import tempfile
        from exakit.ui.tui.panels import ProgressRow
        from exakit.ui.tui.sections import JobView, RunJob
        app, data = await self._open()
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as handle:
            handle.write("2026-10-02 00:00:00 INFO  earlier line\n")
            data.log_file = handle.name
        async with app.run_test(size=(120, 40)) as pilot:
            await self._settled(pilot, app)
            await app.show_section("marketplace")
            await pilot.pause(0.05)
            app.post_message(RunJob("marketplace", "dash-server"))
            seen_running = False
            for _ in range(40):
                await pilot.pause(0.02)
                if app.query(ProgressRow):
                    seen_running = True
                    break
            self.assertTrue(seen_running, "a running row shows while the action runs")
            for _ in range(100):
                await pilot.pause(0.02)
                if not app.job_running and app.query(JobView):
                    break
            self.assertEqual(data.jobs, [("marketplace", "dash-server")])
            await pilot.pause(0.6)
            lines = [t.plain for t in app.query_one(JobView).query_one("LogPane").lines]
            self.assertIn("• running marketplace dash-server", lines)
            self.assertTrue(any(line.startswith("Done: applied") for line in lines))
            self.assertTrue(any("exasol stop -> 0" in line for line in lines), "the log's CMD line is tailed into the view")
            self.assertFalse(any("shown through the renderer already" in line for line in lines), "INFO lines are not shown twice")
            self.assertFalse(any("earlier line" in line for line in lines), "only what the action wrote")
            self.assertFalse(app.query(ProgressRow), "the running row goes when the action ends")
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


@unittest.skipUnless(HAVE_TEXTUAL, "textual is not installed here")
class OneLineRowsTest(unittest.IsolatedAsyncioTestCase):
    """A list row never wraps, whatever the width, so the line under the mouse is the row it opens."""

    def test_the_fit_keeps_the_hint_while_there_is_room_and_cuts_it_otherwise(self):
        from exakit.ui.tui.choices import fit
        self.assertEqual(fit("dash-server", "installed", 16, 40), ("dash-server     ", "installed"))
        self.assertEqual(fit("exasol-vscode", "managed outside the kit", 16, 30), ("exasol-vscode   ", "managed out…"))
        self.assertEqual(fit("exasol-scheduler", "installed", 0, 19), ("exasol-scheduler", ""))
        self.assertEqual(fit("a-very-long-add-on-name", "installed", 0, 10), ("a-very-lo…", ""))

    async def test_a_narrow_list_still_shows_one_line_per_row(self):
        from textual.app import App
        from exakit.ui.tui.choices import ChoiceList
        from exakit.ui.widgets import Option

        class Narrow(App):
            CSS = "ChoiceList { width: 24; }"

            def compose(self):
                yield ChoiceList([Option("dash-server", "dash-server", "installed"), Option("exasol-vscode", "exasol-vscode", "managed outside the kit"),
                                  Option("exasol-scheduler", "exasol-scheduler", "installed")], single=True, marks=False)

        async with Narrow().run_test(size=(60, 10)) as pilot:
            await pilot.pause()
            rows = pilot.app.query_one(ChoiceList).render().plain.split("\n")
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(len(row) <= 24 for row in rows), rows)
            self.assertEqual(rows[0], " ▸ dash-server  install…")


@unittest.skipUnless(HAVE_TEXTUAL, "textual is not installed here")
class CatalogAndCopyTest(unittest.IsolatedAsyncioTestCase):
    def test_the_catalog_detail_carries_the_whole_help_page(self):
        from exakit.ui.tui.sections import catalog_detail
        text = catalog_detail(CATALOG[0], "QUICKSTART\n  exakit start\n").plain
        self.assertIn("QUICKSTART", text)
        self.assertIn("exakit start", text)
        self.assertNotIn("More: exakit help", text)
        self.assertIn("More: exakit help personal", catalog_detail(CATALOG[0]).plain)
        self.assertIn("Managed", catalog_detail({**CATALOG[0], "managed": "database: yours before the kit, adopted into it"}).plain)

    async def test_the_catalog_view_shows_the_help_page_of_the_entry(self):
        from exakit.ui.tui.dashboard import DashboardApp
        data = FakeData()
        app = DashboardApp(data, title="t")
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(400):
                await pilot.pause(0.02)
                if app.state.get("catalog") and app.query("#view"):
                    break
            await app.show_section("catalog")
            await pilot.pause(0.3)
            from textual.widgets import Static
            widget = app.query_one(".detail-text", Static)
            text = getattr(widget, "renderable", None)
            text = widget.content if text is None else text
            self.assertIn("HELP PAGE FOR personal", text.plain if hasattr(text, "plain") else str(text))

    def test_the_copier_gets_the_text_the_app_copies(self):
        from exakit.ui.tui.dashboard import DashboardApp
        from exakit.ui.tui.app import KitApp
        copied: list[str] = []
        DashboardApp(FakeData(), title="t", copier=lambda s: copied.append(s) or True).copy_to_clipboard("one")
        KitApp(title="t", copier=lambda s: copied.append(s) or True).copy_to_clipboard("two")
        self.assertEqual(copied, ["one", "two"])


@unittest.skipUnless(HAVE_TEXTUAL, "textual is not installed here")
class HelpHeaderTest(unittest.TestCase):
    def test_the_boxed_title_of_a_help_page_is_dropped_in_the_catalog(self):
        from exakit.ui.tui.sections import _without_header
        page = "  ----------\n   Exasol Personal (the runtime)\n  The local database.\n  ----------\n\n  The body.\n"
        self.assertEqual(_without_header(page), "  The body.")
        self.assertEqual(_without_header("QUICKSTART\n  exakit start\n"), "QUICKSTART\n  exakit start\n")
