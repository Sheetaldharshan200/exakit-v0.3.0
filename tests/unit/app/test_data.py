import tempfile
import unittest
from pathlib import Path

from exakit.adapters.process.runner import Completed
from exakit.app.loading import data, data_files, data_folder
from exakit.domain.errors import BadInput, Failed
from tests.unit.app.harness import MANIFEST, Sandbox
from tests.unit.fakes import FakeExapump, FakeRuntime

LISTING_EMPTY = Completed(0, "EXAKIT.LISTING_ANSWERED|1\n", "")


def _listing(rows: dict[str, int]) -> Completed:
    return Completed(0, "EXAKIT.LISTING_ANSWERED|1\n" + "".join(f"{k}|{v}\n" for k, v in rows.items()), "")


def _box(pump: FakeExapump, **kw) -> Sandbox:
    box = Sandbox(manifest=MANIFEST, **kw)
    box.ctx.exapump = pump
    box.ctx.runtime = FakeRuntime()
    return box


class BundledTest(unittest.TestCase):
    def test_bundled_datasets_in_order(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            found = data.bundled(box.ctx)
            self.assertEqual([d.id for d in found], ["tpch", "energy", "weather"])
            self.assertEqual(found[0].flag, "data.loaded")
            self.assertEqual(found[1].flag, "data.datasets.energy.loaded")
            self.assertEqual(found[0].markers, ("CUSTOMER", "ORDERS", "LINEITEM"))
            with self.assertRaises(BadInput):
                data.dataset(box.ctx, "nope")
        finally:
            box.close()

    def test_loaded_asks_the_database_and_heals_the_manifest(self):
        pump = FakeExapump([("LISTING_ANSWERED", _listing({"TPCH.CUSTOMER": 1, "TPCH.ORDERS": 1, "TPCH.LINEITEM": 1, "ENERGY.ENERGY_METERS": 50}))])
        box = _box(pump)
        try:
            self.assertEqual(data.loaded(box.ctx), {"tpch"})
            m = box.manifest()
            self.assertTrue(m.get("data.loaded"))
            self.assertFalse(m.get("data.datasets.energy.loaded"))
            self.assertEqual([d.id for d in data.pending(box.ctx)], ["energy", "weather"])
        finally:
            box.close()

    def test_loaded_falls_back_to_the_manifest_when_the_database_is_silent(self):
        box = _box(FakeExapump(default=Completed(1, "", "refused")))
        try:
            self.assertEqual(data.loaded(box.ctx), {"tpch"})
        finally:
            box.close()


class LoadTest(unittest.TestCase):
    def _pump(self, verify="CHECK,OK,fine\n"):
        return FakeExapump([
            ("LISTING_ANSWERED", LISTING_EMPTY),
            ("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")),
            ("EXAKIT_RC[", Completed(0, "EXAKIT_RC[10]", "")),
            ("STATUS", Completed(0, verify, "")),
        ])

    def test_load_runs_schema_uploads_statements_verify_and_records(self):
        pump = self._pump()
        box = _box(pump)
        try:
            result = data.load(box.ctx, data.dataset(box.ctx, "weather"))
            self.assertEqual(result.status, "loaded")
            self.assertEqual(len(pump.uploads), 2)
            self.assertEqual({u[1] for u in pump.uploads}, {"WEATHER.WEATHER_CITIES", "WEATHER.WEATHER_DAILY"})
            m = box.manifest()
            self.assertTrue(m.get("data.datasets.weather.loaded"))
            self.assertEqual(m.get("data.datasets.weather.tables"), 2)
            self.assertEqual(m.get("data.datasets.weather.rows"), 20)
            self.assertEqual(m.get("data.last_load.source"), "dataset:weather")
            self.assertIn("Dataset 'weather' loaded and verified - 2 tables, 20 rows", box.screen())
        finally:
            box.close()

    def test_verification_failure_is_reported_and_not_marked(self):
        box = _box(self._pump(verify="CHECK,FAIL,bad\n"))
        try:
            with self.assertRaises(Failed) as ctx:
                data.load(box.ctx, data.dataset(box.ctx, "weather"))
            self.assertIn("--force", str(ctx.exception))
            self.assertFalse(box.manifest().get("data.datasets.weather.loaded"))
        finally:
            box.close()

    def test_already_loaded_skips_unless_forced(self):
        pump = FakeExapump([("LISTING_ANSWERED", _listing({"WEATHER.WEATHER_CITIES": 10, "WEATHER.WEATHER_DAILY": 10}))])
        box = _box(pump)
        try:
            self.assertEqual(data.load(box.ctx, data.dataset(box.ctx, "weather")).status, "already loaded")
            self.assertEqual(pump.uploads, [])
        finally:
            box.close()


class CommandTest(unittest.TestCase):
    def test_env_datasets_and_force(self):
        pump = FakeExapump([("LISTING_ANSWERED", LISTING_EMPTY), ("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")),
                            ("EXAKIT_RC[", Completed(0, "EXAKIT_RC[1]", "")), ("STATUS", Completed(0, "x,OK,y", ""))])
        box = _box(pump, env={"EXAKIT_DATASETS": "weather,nope"})
        try:
            result = data.data_load(box.ctx, [])
            self.assertEqual(result.status, "loaded")
            self.assertEqual({u[1] for u in pump.uploads}, {"WEATHER.WEATHER_CITIES", "WEATHER.WEATHER_DAILY"})
            with self.assertRaises(BadInput):
                data.data_load(box.ctx, ["--nope"])
        finally:
            box.close()

    def test_non_interactive_menu_loads_pending_defaults(self):
        pump = FakeExapump([("LISTING_ANSWERED", _listing({"TPCH.CUSTOMER": 1, "TPCH.ORDERS": 1, "TPCH.LINEITEM": 1})),
                            ("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")),
                            ("EXAKIT_RC[", Completed(0, "EXAKIT_RC[1]", "")), ("STATUS", Completed(0, "x,OK,y", ""))])
        box = _box(pump)
        try:
            data.data_load(box.ctx, [])
            targets = {u[1].split(".")[0] for u in pump.uploads}
            self.assertEqual(targets, {"ENERGY", "WEATHER"})
        finally:
            box.close()


class FilesTest(unittest.TestCase):
    def test_table_names_and_kinds(self):
        self.assertEqual(data_files.table_name_from_path(Path("Sales Data-2024.csv")), "SALES_DATA_2024")
        self.assertEqual(data_files.table_name_from_path(Path("x.csv.gz")), "X_CSV")
        self.assertEqual(data_files.table_name_from_path(Path("__.csv")), "MY_TABLE")
        self.assertEqual(data_files.file_kind(Path("a.GeoJSON")), "json")
        self.assertEqual(data_files.file_kind(Path("a.parquet")), "parquet")
        self.assertEqual(data_files.file_kind(Path("a.csv.gz")), "csv")
        self.assertEqual(data_files.file_kind(Path("a.png")), "unknown")

    def test_inspect_csv(self):
        box = Sandbox()
        try:
            p = Path(box.tmp.name) / "a.csv"
            p.write_bytes(b"\xef\xbb\xbfa;b\r\n1;2\r\n")
            info = data_files.inspect_csv(p)
            self.assertEqual((info.delimiter, info.flags), (";", ("bom", "crlf")))
            p.write_bytes(b"a\tb\n1\t2\n")
            self.assertEqual(data_files.inspect_csv(p).delimiter, "\t")
            p.write_bytes(b"a,b\n")
            self.assertIsNone(data_files.inspect_csv(p))
        finally:
            box.close()

    def test_scan_folder_classifies_files(self):
        box = Sandbox()
        try:
            folder = Path(box.tmp.name) / "f"
            (folder / "sub").mkdir(parents=True)
            (folder / "aaa.csv").write_text("a,b\n1,2\n")
            (folder / "sales.csv").write_text("a,b\n1,2\n")
            (folder / "orders.csv").write_text("x,y\n3,4\n")
            (folder / "orders.parquet").write_bytes(b"PAR1xxxx")
            (folder / "empty.csv").write_text("")
            (folder / "head.csv").write_text("a,b\n")
            (folder / "stops.txt").write_text("a,b\n1,2\n")
            (folder / "readme.txt").write_text("hello\n")
            (folder / "pic.png").write_bytes(b"x")
            (folder / ".hidden.csv").write_text("a\n1\n")
            (folder / "sub" / "inner.csv").write_text("a\n1\n")
            entries = {e.path.name: e for e in data_folder.scan_folder(folder)}
            self.assertEqual(entries["aaa.csv"].action, "load")
            self.assertEqual((entries["sales.csv"].kind, entries["sales.csv"].table), ("duplicate-content", "aaa.csv"))
            self.assertEqual(entries["orders.csv"].action, "load")
            self.assertEqual((entries["orders.parquet"].kind, entries["orders.parquet"].table), ("duplicate-table", "orders.csv"))
            self.assertEqual(entries["empty.csv"].kind, "empty")
            self.assertEqual(entries["head.csv"].kind, "header-only")
            self.assertEqual(entries["stops.txt"].kind, "extension")
            self.assertEqual(entries["readme.txt"].kind, "unsupported")
            self.assertEqual(entries["pic.png"].kind, "unsupported")
            self.assertNotIn(".hidden.csv", entries)
            self.assertNotIn("inner.csv", entries)
        finally:
            box.close()

    def test_receipts_and_decisions(self):
        box = Sandbox()
        try:
            f = Path(box.tmp.name) / "sales.csv"
            f.write_text("a,b\n1,2\n")
            receipts = data_files.Receipts.load(Path(box.tmp.name) / "receipts.tsv")
            entry = data_folder.ScanEntry("load", "csv", "SALES", f)
            inflight = Path(box.tmp.name) / "inflight"
            self.assertEqual(data_folder._decide(entry, "S", None, receipts, inflight), ("load", "unknown"))
            self.assertEqual(data_folder._decide(entry, "S", {}, receipts, inflight), ("load", "absent"))
            self.assertEqual(data_folder._decide(entry, "S", {"S.SALES": 0}, receipts, inflight), ("load", "0"))
            self.assertEqual(data_folder._decide(entry, "S", {"S.SALES": 5}, receipts, inflight), ("clash", "5"))
            receipts.record("S.SALES", f, 5)
            self.assertEqual(data_folder._decide(entry, "S", {"S.SALES": 5}, receipts, inflight), ("done", "5"))
            self.assertEqual(data_folder._decide(entry, "S", {"S.SALES": 7}, receipts, inflight), ("clash", "7"))
            inflight.write_text("S.SALES")
            self.assertEqual(data_folder._decide(entry, "S", {"S.SALES": 7}, receipts, inflight), ("resume", "7"))
            receipts.forget("S.SALES")
            self.assertEqual(receipts.rows, [])
        finally:
            box.close()

    def test_pieces_keep_the_header_and_even_quotes(self):
        box = Sandbox()
        try:
            f = Path(box.tmp.name) / "big.csv"
            rows = ["h1,h2"] + [f'{i},"multi\nline"' if i % 7 == 0 else f"{i},v{i}" for i in range(200)]
            f.write_text("\n".join(rows) + "\n")
            pieces = data_files._split_pieces(f, 400, Path(box.tmp.name))
            self.assertGreater(len(pieces), 1)
            body = ""
            for piece in pieces:
                text = piece.read_text()
                self.assertTrue(text.startswith("h1,h2\n"))
                self.assertEqual(text.count('"') % 2, 0)
                body += text[len("h1,h2\n"):]
            self.assertEqual(body, "\n".join(rows[1:]) + "\n")
        finally:
            box.close()

    def test_upload_recovery_retries_only_cut_transfers(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            f = Path(box.tmp.name) / "a.csv"
            f.write_text("a\n1\n")
            pump = FakeExapump(default=Completed(1, "Error: ETL-5105 transfer closed", ""))
            box.env["EXAKIT_UPLOAD_RETRIES"] = "1"
            self.assertFalse(data_files.upload_with_recovery(box.ctx, pump, f, "S.A"))
            self.assertEqual(len(pump.uploads), 2)
            pump = FakeExapump(default=Completed(1, "Error: parse error row=3", ""))
            self.assertFalse(data_files.upload_with_recovery(box.ctx, pump, f, "S.A"))
            self.assertEqual(len(pump.uploads), 1)
        finally:
            box.close()

    def test_load_folder_end_to_end(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            folder = Path(box.tmp.name) / "exports"
            folder.mkdir()
            (folder / "sales.csv").write_text("a,b\n1,2\n")
            (folder / "orders.csv").write_text("a;b\n1;2\n")
            listing_after = _listing({"EXPORTS.SALES": 1, "EXPORTS.ORDERS": 1})

            class StatefulPump(FakeExapump):
                listings = 0

                def sql(self, profile, text, **kw):
                    if "LISTING_ANSWERED" in text:
                        self.listings += 1
                        return LISTING_EMPTY if self.listings == 1 else listing_after
                    return super().sql(profile, text, **kw)

            pump = StatefulPump([("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", ""))])
            box.ctx.exapump = pump
            box.ctx.runtime = FakeRuntime()
            result = data_folder.load_folder(box.ctx, folder)
            self.assertEqual(result.status, "loaded")
            self.assertEqual({(u[1], u[3]) for u in pump.uploads}, {("EXPORTS.SALES", ","), ("EXPORTS.ORDERS", ";")}, "the folder's name is the schema")
            self.assertIn("EXPORTS: 2 files loaded", box.screen())
            m = box.manifest()
            self.assertEqual(m.get("data.last_load.type"), "local_folder")
            self.assertEqual(m.get("data.last_load.files"), 2)
            receipts = data_files.Receipts.load(box.ctx.paths.cache / "load-receipts.tsv")
            self.assertEqual({r[0] for r in receipts.rows}, {"EXPORTS.SALES", "EXPORTS.ORDERS"})
            box.out.truncate(0)
            box.out.seek(0)
            pump.uploads.clear()
            result = data_folder.load_folder(box.ctx, folder)
            self.assertEqual(pump.uploads, [])
            self.assertIn("already holds every file", box.screen())
        finally:
            box.close()

    def test_clash_without_terminal_skips(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            folder = Path(box.tmp.name) / "exports"
            folder.mkdir()
            (folder / "sales.csv").write_text("a,b\n1,2\n")
            pump = FakeExapump([("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")), ("LISTING_ANSWERED", _listing({"EXPORTS.SALES": 9}))])
            box.ctx.exapump = pump
            data_folder.load_folder(box.ctx, folder)
            self.assertEqual(pump.uploads, [])
            self.assertIn("not loaded: the table already holds rows this kit did not put there", box.screen())
            self.assertIn("already holds every file", box.screen())
            box.env["EXAKIT_ON_EXISTING"] = "replace"
            data_folder.load_folder(box.ctx, folder)
            self.assertTrue(any("DROP TABLE IF EXISTS EXPORTS.SALES" in t for _, t in pump.calls))
            self.assertEqual(len(pump.uploads), 1)
        finally:
            box.close()


if __name__ == "__main__":
    unittest.main()


def _tree(root: Path, layout: dict[str, str]) -> Path:
    """Write ``layout`` (relative path -> CSV body) under ``root``."""
    for rel, body in layout.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)
    return root


class NamesTest(unittest.TestCase):
    """Every name the loader makes is usable unquoted in Exasol."""

    def test_identifiers_start_with_a_letter_avoid_reserved_words_and_fit_the_limit(self):
        from exakit.app.loading.names import MAX_IDENTIFIER, identifier
        self.assertEqual(identifier("my-data", lead="DATA"), "MY_DATA")
        self.assertEqual(identifier("2024", lead="DATA"), "DATA_2024")
        self.assertEqual(identifier("order", lead="DATA"), "ORDER_DATA")
        self.assertEqual(identifier("données", lead="DATA"), "DONNEES")
        self.assertEqual(identifier("--", lead="DATA"), "DATA")
        long_a, long_b = identifier("x" * 200 + "a", lead="DATA"), identifier("x" * 200 + "b", lead="DATA")
        self.assertEqual((len(long_a), len(long_b)), (MAX_IDENTIFIER, MAX_IDENTIFIER))
        self.assertNotEqual(long_a, long_b, "two long names stay apart")

    def test_a_typed_name_is_refused_with_the_reason(self):
        from exakit.app.loading.names import problem
        self.assertIsNone(problem("sales"))
        self.assertIn("reserved SQL word (try ORDER_DATA)", problem("order"))
        self.assertIn("starts with a letter", problem("2024"))
        self.assertIn("starts with a letter", problem("_x"))

    def test_the_keyword_answer_is_parsed(self):
        from exakit.app.loading.names import parse_keywords
        self.assertEqual(parse_keywords("K\nEXAKIT_KW[ABSOLUTE,ORDER,ZONE]\n"), {"ABSOLUTE", "ORDER", "ZONE"})
        self.assertEqual(parse_keywords("nothing"), frozenset())

    def test_table_names_follow_the_same_rule_and_ordinary_names_do_not_change(self):
        self.assertEqual(data_files.table_name_from_path(Path("sales.csv")), "SALES")
        self.assertEqual(data_files.table_name_from_path(Path("Sales Q1.csv.gz")), "SALES_Q1_CSV")
        self.assertEqual(data_files.table_name_from_path(Path("2024.csv")), "T_2024")
        self.assertEqual(data_files.table_name_from_path(Path("order.csv")), "ORDER_DATA")


class TreeTest(unittest.TestCase):
    """A folder tree: one schema per folder, named by its own path under the folder that was named."""

    LAYOUT = {"customers.csv": "id\n1\n", "orders.csv": "id\n2\n", "products.csv": "id\n3\n",
              **{f"{side}/{name}.csv": f"id\n{side}{name}\n" for side in ("north", "south") for name in ("sales", "returns")},
              **{f"{side}/archive/day{i}.csv": f"id\n{side}{i}\n" for side in ("north", "south") for i in range(1, 6)}}

    def test_the_users_layout_gives_one_clear_schema_per_folder(self):
        from exakit.app.loading import data_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp) / "my-data", self.LAYOUT)
            plans = data_tree.scan_tree(root)
            self.assertEqual([(p.path.relative_to(root.parent).as_posix(), p.schema, len(p.loadable)) for p in plans],
                             [("my-data", "MY_DATA", 3), ("my-data/north", "NORTH", 2), ("my-data/north/archive", "NORTH_ARCHIVE", 5),
                              ("my-data/south", "SOUTH", 2), ("my-data/south/archive", "SOUTH_ARCHIVE", 5)])

    def test_a_folder_keeps_its_schema_when_folders_are_added_beside_it(self):
        from exakit.app.loading import data_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp) / "my-data", {"north/archive/day1.csv": "id\n1\n"})
            before = {p.path: p.schema for p in data_tree.scan_tree(root)}
            _tree(root, {"south/archive/day1.csv": "id\n2\n", "east/x.csv": "id\n3\n"})
            after = {p.path: p.schema for p in data_tree.scan_tree(root)}
            self.assertEqual(after[root / "north" / "archive"], before[root / "north" / "archive"])
            self.assertEqual(before[root / "north" / "archive"], "NORTH_ARCHIVE")

    def test_folders_that_fold_to_one_name_are_told_apart(self):
        from exakit.app.loading import data_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp) / "data", {"a.csv": "id\n1\n", "data/b.csv": "id\n2\n", "north/archive/c.csv": "id\n3\n",
                                                "north_archive/d.csv": "id\n4\n", "north-archive/e.csv": "id\n5\n"})
            names = [p.schema for p in data_tree.scan_tree(root)]
            self.assertEqual(len(names), len(set(names)), names)
            self.assertEqual(names, ["DATA", "DATA_DATA", "NORTH_ARCHIVE", "DATA_NORTH_ARCHIVE", "NORTH_ARCHIVE_2"])

    def test_digits_reserved_words_hidden_and_linked_folders(self):
        from exakit.app.loading import data_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp) / "exports", {"2024/a.csv": "id\n1\n", "order/b.csv": "id\n2\n", ".cache/c.csv": "id\n3\n"})
            (root / "linked").symlink_to(root / "2024")
            self.assertEqual([p.schema for p in data_tree.scan_tree(root)], ["DATA_2024", "ORDER_DATA"])

    def test_the_databases_own_reserved_words_are_honoured(self):
        from exakit.app.loading import data_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp) / "exports", {"north/a.csv": "id\n1\n"})
            self.assertEqual([p.schema for p in data_tree.scan_tree(root, reserved=frozenset({"NORTH"}))], ["NORTH_DATA"])

    def test_unattended_every_folder_loads_and_the_env_names_the_top_schema(self):
        from exakit.app.loading import data_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp) / "exports", {"top.csv": "id\n1\n", "orders/o.csv": "id\n2\n", "mine/m.csv": "id\n3\n"})
            plans = data_tree.scan_tree(root, top_schema="MINE")
            self.assertEqual([p.schema for p in plans], ["MINE", "EXPORTS_MINE", "ORDERS"], "the given name wins; the folder called mine steps aside")
        box = Sandbox(manifest=MANIFEST)
        try:
            self.assertEqual(data_tree.choose_plans(box.ctx, plans), plans)
        finally:
            box.close()

    def test_a_bad_schema_name_in_the_environment_is_refused_before_anything_loads(self):
        box = Sandbox(manifest=MANIFEST, env={"EXAKIT_SCHEMA": "order"})
        try:
            root = _tree(Path(box.tmp.name) / "exports", {"a.csv": "id\n1\n"})
            box.ctx.exapump = FakeExapump([("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", ""))])
            with self.assertRaises(BadInput) as caught:
                data_folder.load_folder(box.ctx, root)
            self.assertIn("ORDER is a reserved SQL word", caught.exception.message)
            self.assertEqual(box.ctx.exapump.uploads, [])
        finally:
            box.close()

    def test_a_tree_loads_each_folder_into_its_own_schema_with_the_live_keyword_list(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            root = _tree(Path(box.tmp.name) / "exports", {"sales.csv": "a,b\n1,2\n", "orders/lines.csv": "a,b\n1,2\n",
                                                           "orders/archive/old.csv": "a,b\n3,4\n", "zone/z.csv": "a,b\n5,6\n"})
            pump = FakeExapump([("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")), ("LISTING_ANSWERED", LISTING_EMPTY),
                                ("EXA_SQL_KEYWORDS", Completed(0, "EXAKIT_KW[ZONE]", ""))])
            box.ctx.exapump = pump
            box.ctx.runtime = FakeRuntime()
            result = data_folder.load_folder(box.ctx, root)
            self.assertEqual(result.data["schemas"], ["EXPORTS", "ORDERS", "ORDERS_ARCHIVE", "ZONE_DATA"])
            self.assertEqual({u[1] for u in pump.uploads}, {"EXPORTS.SALES", "ORDERS.LINES", "ORDERS_ARCHIVE.OLD", "ZONE_DATA.Z"})
            self.assertIn("archive/ -> ORDERS_ARCHIVE", box.screen())
            self.assertEqual(box.manifest().get("data.last_load.target"), "EXPORTS, ORDERS, ORDERS_ARCHIVE, ZONE_DATA")
        finally:
            box.close()

    def test_without_the_keyword_answer_the_built_in_list_names_things_the_same(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            root = _tree(Path(box.tmp.name) / "exports", {"order/a.csv": "a,b\n1,2\n"})
            pump = FakeExapump([("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")), ("LISTING_ANSWERED", LISTING_EMPTY),
                                ("EXA_SQL_KEYWORDS", Completed(1, "", "connection lost"))])
            box.ctx.exapump = pump
            box.ctx.runtime = FakeRuntime()
            self.assertEqual(data_folder.load_folder(box.ctx, root).data["schemas"], ["ORDER_DATA"])
        finally:
            box.close()


class DryRunTest(unittest.TestCase):
    """``exakit data-load --dry-run``: the plan an agent shows before loading, with nothing loaded and no database needed."""

    def _box(self, **env):
        box = Sandbox(manifest=MANIFEST, env=env)
        box.ctx.dry_run = True
        box.ctx.runtime = FakeRuntime("stopped")
        box.ctx.exapump = FakeExapump([])
        return box

    def test_a_folder_tree_plans_schemas_files_and_ignored_entries(self):
        box = self._box()
        try:
            root = _tree(Path(box.tmp.name) / "my-data", {"a.csv": "id\n1\n", "b.csv": "id\n1\n", "notes.pdf": "x",
                                                           "north/archive/day1.csv": "id\n2\n"})
            result = data.data_load(box.ctx, [str(root)])
            self.assertEqual(result.status, "planned")
            self.assertEqual(result.remedy, f"exakit data-load {root}")
            schemas = {s["schema"]: s for s in result.data["schemas"]}
            self.assertEqual(sorted(schemas), ["MY_DATA", "NORTH_ARCHIVE"])
            self.assertEqual([f["table"] for f in schemas["MY_DATA"]["files"]], ["A"])
            reasons = {Path(i["file"]).name: i["reason"] for i in schemas["MY_DATA"]["ignored"]}
            self.assertEqual(reasons["notes.pdf"], "not a CSV, Parquet or JSON file")
            self.assertIn("identical to another file", reasons["b.csv"])
            self.assertEqual(result.data["reserved_words"], "built-in")
            self.assertEqual(box.ctx.exapump.uploads, [])
            self.assertEqual(box.ctx.runtime.started, 0, "a dry run never starts the database")
            self.assertIn("nothing was loaded", box.screen())
        finally:
            box.close()

    def test_a_file_plans_its_target_and_the_datasets_plan_without_a_path(self):
        box = self._box(EXAKIT_DATASETS="tpch,nope")
        try:
            f = Path(box.tmp.name) / "2024.csv"
            f.write_text("id\n1\n")
            self.assertEqual(data.data_load(box.ctx, [str(f)]).data["target"], "STARTER_KIT.T_2024")
            rows = data.data_load(box.ctx, []).data["datasets"]
            self.assertEqual([(r["id"], r["schema"]) for r in rows], [("tpch", "TPCH")], "what would load; an unknown id is warned about, as in a real run")
            self.assertIn("Unknown dataset id 'nope'", box.screen())
        finally:
            box.close()

    def test_a_missing_path_is_refused(self):
        box = self._box()
        try:
            with self.assertRaises(Failed):
                data.data_load(box.ctx, [str(Path(box.tmp.name) / "nope")])
        finally:
            box.close()


class FolderFilesTest(unittest.TestCase):
    def test_a_folder_load_answers_with_one_row_per_file(self):
        box = Sandbox(manifest=MANIFEST)
        try:
            root = _tree(Path(box.tmp.name) / "exports", {"sales.csv": "a,b\n1,2\n", "readme.md": "x"})
            box.ctx.exapump = FakeExapump([("EXA_ALL_SCHEMAS", Completed(0, "EXAKIT_SCHEMA_PRESENT", "")), ("LISTING_ANSWERED", LISTING_EMPTY)])
            box.ctx.runtime = FakeRuntime()
            files = {Path(f["file"]).name: f for f in data_folder.load_folder(box.ctx, root).data["files"]}
            self.assertEqual((files["sales.csv"]["schema"], files["sales.csv"]["table"], files["sales.csv"]["status"]), ("EXPORTS", "SALES", "loaded"))
            self.assertEqual((files["readme.md"]["status"], files["readme.md"]["reason"]), ("ignored", "unsupported"))
        finally:
            box.close()
