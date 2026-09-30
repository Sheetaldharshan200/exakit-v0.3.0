"""Your own data: one file, a folder of files, JSON through the json-tables engine, and the receipts.

Uploads go through exapump, which infers the schema, creates the table if
needed and appends. A cut-short transfer is retried; a large CSV is re-sent
in pieces through a staging table so one bad chunk never leaves a half
table behind. A folder load remembers what it loaded (receipts keyed by
size and content hash), so re-running it is safe.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from exakit.adapters.exapump import Exapump, LISTING_SQL, failure_reason, table_listing
from exakit.domain.errors import BadInput, Failed
from exakit.domain.manifest import Manifest
from exakit.domain.result import Result

from . import Context
from .runtime_ops import exapump, profile_name

CUT_SHORT = ("ETL-5105", "transfer closed with outstanding read data", "Transferred a partial file", "Connection reset by peer",
             "connection was aborted")
COMPRESSED = (".gz", ".bz2", ".zst", ".xz")


# --- names and kinds -------------------------------------------------------------------


def table_name_from_path(path: Path) -> str:
    stem = path.name.split("?")[0].rsplit(".", 1)[0] if "." in path.name else path.name
    name = re.sub(r"[^A-Z0-9_]", "_", stem.upper()).strip("_")
    name = re.sub(r"_+", "_", name)
    return name or "MY_TABLE"


def file_kind(path: Path) -> str:
    name = path.name.lower()
    for ext in COMPRESSED:
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    if name.endswith((".json", ".geojson", ".ndjson", ".jsonl")):
        return "json"
    if name.endswith((".parquet", ".pq")):
        return "parquet"
    if name.endswith((".csv", ".tsv", ".txt")):
        return "csv"
    return "unknown"


def valid_target(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+", text))


@dataclass(frozen=True, slots=True)
class CsvInfo:
    delimiter: str
    flags: tuple[str, ...]

    @property
    def delimiter_name(self) -> str:
        return {",": "comma", ";": "semicolon", "\t": "tab"}[self.delimiter]


def inspect_csv(path: Path) -> CsvInfo | None:
    """Delimiter and flags (bom, crlf) from the header; None for a header with no rows."""
    if path.name.lower().endswith(COMPRESSED):
        return CsvInfo(",", ())
    with path.open("rb") as handle:
        first = handle.readline()
        second = handle.readline()
    flags: list[str] = []
    if first.startswith(b"\xef\xbb\xbf"):
        flags.append("bom")
        first = first[3:]
    if first.endswith(b"\r\n"):
        flags.append("crlf")
    if not second.strip():
        return None
    header = first.decode("utf-8", errors="replace")
    delimiter = "," if "," in header else ";" if ";" in header else "\t"
    return CsvInfo(delimiter, tuple(flags))


# --- uploads with recovery -------------------------------------------------------------------


def _cut_short(text: str) -> bool:
    return any(s in text for s in CUT_SHORT)


def _split_pieces(path: Path, piece_bytes: int, out_dir: Path) -> list[Path]:
    """Cut a CSV at line boundaries where the running quote count is even; every piece keeps the header."""
    pieces: list[Path] = []
    with path.open("rb") as handle:
        header = handle.readline()
        index, size, quotes, chunk = 0, 0, 0, []
        for line in handle:
            chunk.append(line)
            size += len(line)
            quotes += line.count(b'"')
            if size >= piece_bytes and quotes % 2 == 0:
                piece = out_dir / f"{path.stem}.piece{index:04d}{path.suffix}"
                piece.write_bytes(header + b"".join(chunk))
                pieces.append(piece)
                index, size, chunk = index + 1, 0, []
        if chunk:
            piece = out_dir / f"{path.stem}.piece{index:04d}{path.suffix}"
            piece.write_bytes(header + b"".join(chunk))
            pieces.append(piece)
    return pieces


def upload_with_recovery(ctx: Context, pump: Exapump, file: Path, table: str, *, delimiter: str | None = None) -> bool:
    """Upload one file; on a cut-short transfer retry, in pieces for a large CSV. True when the rows landed."""
    retries_text = ctx.env.get("EXAKIT_UPLOAD_RETRIES", "")
    retries = int(retries_text) if retries_text.isdigit() else 2
    done = pump.upload(file, table, profile_name(ctx), delimiter=delimiter)
    ctx.log.line("CMD", f"exapump upload {file.name} --table {table} -> {done.code}")
    if done.ok:
        return True
    ctx.log.line("ERROR", (done.err or done.out).strip()[-800:])
    retryable = _cut_short(done.out + done.err) or not (done.out + done.err).strip()
    if not retryable or retries == 0:
        return False
    piece_kb_text = ctx.env.get("EXAKIT_UPLOAD_PIECE_KB", "")
    piece_kb = int(piece_kb_text) if piece_kb_text.isdigit() else 128
    size = file.stat().st_size
    if file.suffix.lower() in (".csv", ".tsv", ".txt") and piece_kb and size > piece_kb * 1024 and size <= 64 * 1024 * 1024:
        return _upload_pieces(ctx, pump, file, table, piece_kb * 1024, retries, delimiter)
    for attempt in range(2, retries + 2):
        ctx.log.line("WARN", f"{file.name}: the import connection was cut mid-transfer - attempt {attempt} of {retries + 1}")
        time.sleep(attempt - 1)
        done = pump.upload(file, table, profile_name(ctx), delimiter=delimiter)
        if done.ok:
            return True
        if not _cut_short(done.out + done.err) and (done.out + done.err).strip():
            return False
    return False


def _upload_pieces(ctx: Context, pump: Exapump, file: Path, table: str, piece_bytes: int, retries: int, delimiter: str | None) -> bool:
    stage = f"{table}__EXAKIT_PIECES"
    profile = profile_name(ctx)
    with tempfile.TemporaryDirectory(prefix="exakit-pieces-") as tmp:
        pieces = _split_pieces(file, piece_bytes, Path(tmp))
        if not pump.sql(profile, f"DROP TABLE IF EXISTS {stage}").ok or not pump.sql(profile, f"CREATE TABLE {stage} LIKE {table}").ok:
            return False
        for piece in pieces:
            ok = False
            for attempt in range(retries + 1):
                if attempt:
                    time.sleep(attempt)
                if pump.upload(piece, stage, profile, delimiter=delimiter).ok:
                    ok = True
                    break
            if not ok:
                pump.sql(profile, f"DROP TABLE IF EXISTS {stage}")
                return False
        moved = pump.sql(profile, f"INSERT INTO {table} SELECT * FROM {stage}")
        pump.sql(profile, f"DROP TABLE {stage}")
        return moved.ok


# --- receipts (what a folder load already put where) ---------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class Receipts:
    path: Path
    rows: list[list[str]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Receipts":
        rows = []
        if path.is_file():
            rows = [l.split("\t") for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return cls(path, rows)

    def record(self, target: str, file: Path, rows: int) -> None:
        self.rows.append([target.upper(), str(file.stat().st_size), _sha256(file), str(rows), str(int(time.time())), file.name])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\t".join(self.rows[-1]) + "\n")

    def forget(self, target: str) -> None:
        self.rows = [r for r in self.rows if r[0] != target.upper()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join("\t".join(r) + "\n" for r in self.rows), encoding="utf-8")

    def match(self, target: str, file: Path) -> int | None:
        """The recorded row count when the newest receipt for the target is this exact file."""
        size = str(file.stat().st_size)
        for row in reversed(self.rows):
            if row[0] == target.upper():
                if row[1] == size and row[2] == _sha256(file):
                    return int(row[3])
                return None
        return None


# --- JSON through the json-tables engine ---------------------------------------------------


def json_tables_bin(ctx: Context) -> Path | None:
    bin_path = Path(ctx.env.get("EXAKIT_JSON_TABLES_BIN") or ctx.paths.bin_dir / "exasol-json-tables")
    return bin_path if bin_path.exists() else None


def normalise_json(path: Path, out_dir: Path) -> Path:
    """One JSON document (or array) to NDJSON; NDJSON stays as it is; malformed raises BadInput."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        doc = json.loads(text)
    except ValueError:
        lines = [l for l in text.splitlines() if l.strip()]
        try:
            for line in lines:
                json.loads(line)
            return path
        except ValueError:
            raise BadInput(f"{path} is not valid JSON")
    out = out_dir / (path.stem + ".ndjson")
    with out.open("w", encoding="utf-8") as handle:
        for item in (doc if isinstance(doc, list) else [doc]):
            handle.write(json.dumps(item) + "\n")
    return out


def load_json(ctx: Context, pump: Exapump, path: Path, target: str) -> list[str]:
    """Shred a JSON file into tables with the json-tables engine. Returns the targets loaded."""
    engine = json_tables_bin(ctx)
    if engine is None:
        from .marketplace import install_addon_quietly  # noqa: PLC0415 - JSON needs the add-on; installed on demand
        if not install_addon_quietly(ctx, "json-tables") or json_tables_bin(ctx) is None:
            raise Failed("JSON loading needs the JSON Tables add-on, which could not be installed - see: exakit logs setup",
                         remedy="exakit marketplace json-tables")
        engine = json_tables_bin(ctx)
    with tempfile.TemporaryDirectory(prefix="exakit-json-") as tmp:
        work = Path(tmp)
        source = normalise_json(path, work)
        out_dir = work / "out"
        done = ctx.runner.run([str(engine), "ingest", "--input", str(source), "--output-dir", str(out_dir)], timeout=3600)
        ctx.log.line("CMD", f"exasol-json-tables ingest {source.name} -> {done.code}")
        if not done.ok:
            ctx.log.line("ERROR", (done.err or done.out).strip()[-800:])
            raise Failed(f"JSON Tables could not shred {path.name} - see: exakit logs json-tables", remedy="exakit logs json-tables")
        parquets = sorted(out_dir.rglob("*.parquet")) if out_dir.exists() else []
        if not parquets:
            raise Failed(f"JSON Tables produced no tables from {path.name}.")
        schema, _, table = target.rpartition(".")
        ensure_schema_for(ctx, pump, schema)
        targets: list[str] = []
        for parquet in parquets:
            dest = target if len(parquets) == 1 else f"{schema}.{table}_{table_name_from_path(parquet)}"
            if not upload_with_recovery(ctx, pump, parquet, dest):
                raise Failed(f"Could not load {parquet.name} into {dest} - see: exakit logs setup", remedy="exakit logs setup")
            targets.append(dest)
        return targets


def ensure_schema_for(ctx: Context, pump: Exapump, schema: str) -> None:
    from .data import ensure_schema  # noqa: PLC0415 - shared with the dataset loader
    ensure_schema(ctx, pump, schema)


# --- one file ----------------------------------------------------------------------------------


def load_local_path(ctx: Context, path: Path) -> Result:
    if path.is_dir():
        return load_folder(ctx, path)
    return load_file(ctx, path)


def load_file(ctx: Context, path: Path) -> Result:
    pump = exapump(ctx)
    if pump is None:
        raise Failed("exapump (the data-loading CLI) is not installed", remedy="exakit update")
    if not path.is_file() or not path.stat().st_size:
        raise Failed(f"File not found or empty: {path}")
    kind = file_kind(path)
    if kind == "csv" and not path.name.lower().endswith((".csv", ".csv.gz")):
        raise Failed(f"{path.name} looks tabular but exapump reads .csv and .parquet only - rename it to .csv and retry.")
    if kind == "unknown":
        raise Failed(f"{path.name} is not a CSV, Parquet or JSON file the kit can load.")
    schema = (ctx.env.get("EXAKIT_SCHEMA") or "STARTER_KIT").upper()
    default_target = ctx.env.get("EXAKIT_DATA_TABLE") or f"{schema}.{table_name_from_path(path)}"
    target = ctx.ui.prompt("Target table (SCHEMA.TABLE, back to return)", default_target) if ctx.ui.interactive else default_target
    if target.lower() in ("b", "back"):
        return Result(True, "cancelled")
    if not valid_target(target):
        raise BadInput(f"'{target}' is not SCHEMA.TABLE (letters, digits and underscores).")
    target = target.upper()
    if kind == "json":
        targets = load_json(ctx, pump, path, target)
        _record_last_load(ctx, "local_json", ",".join(targets), str(path))
        ctx.ui.ok(f"Loaded {path} into {', '.join(targets)}")
        return Result(True, "loaded", data={"targets": targets})
    info = inspect_csv(path) if kind == "csv" else None
    if kind == "csv" and info is None:
        raise Failed(f"{path.name} has a header and no rows - nothing to load.")
    ensure_schema_for(ctx, pump, target.rpartition(".")[0])
    delimiter = info.delimiter if info else None
    if not upload_with_recovery(ctx, pump, path, target, delimiter=delimiter):
        reason = failure_reason(_log_tail(ctx), delimiter_name=info.delimiter_name if info else "comma", crlf=bool(info and "crlf" in info.flags))
        raise Failed(f"Could not load {path.name} into {target} - {reason}", remedy="exakit logs setup")
    if info and "crlf" in info.flags:
        ctx.ui.warn("The file has Windows line endings, so every value in the last column ends in a carriage return.")
    _record_last_load(ctx, "local_file", target, str(path))
    ctx.ui.ok(f"Loaded {path} into {target}")
    return Result(True, "loaded", data={"targets": [target]})


def _log_tail(ctx: Context) -> str:
    try:
        return ctx.log.path.read_text(encoding="utf-8", errors="replace")[-4000:] if ctx.log.path else ""
    except OSError:
        return ""


def _record_last_load(ctx: Context, kind: str, target: str, source: str, files: int | None = None) -> None:
    def change(m: Manifest) -> None:
        m.set("data.last_load.type", kind)
        m.set("data.last_load.target", target)
        m.set("data.last_load.source", source)
        if files is not None:
            m.set("data.last_load.files", files)
    ctx.manifest_store.update(change)


# --- a folder ------------------------------------------------------------------------------------


@dataclass(slots=True)
class ScanEntry:
    action: str        # load | skip
    kind: str          # csv | parquet | json | unsupported | empty | header-only | extension | duplicate-table | duplicate-content
    table: str         # target table, or the first file's name for duplicates
    path: Path


def scan_folder(folder: Path) -> list[ScanEntry]:
    entries: list[ScanEntry] = []
    seen_tables: dict[str, Path] = {}
    seen_sizes: dict[int, list[tuple[Path, str]]] = {}
    for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
        size = path.stat().st_size
        if not size:
            entries.append(ScanEntry("skip", "empty", "", path))
            continue
        kind = file_kind(path)
        lower = path.name.lower()
        if kind == "csv" and (lower.endswith(".txt") or lower.endswith(".tsv") or any(lower.endswith(".txt" + c) for c in COMPRESSED)):
            if lower.endswith(".txt") and _looks_tabular(path) or lower.endswith(".tsv"):
                entries.append(ScanEntry("skip", "extension", "", path))
            else:
                entries.append(ScanEntry("skip", "unsupported", "", path))
            continue
        if kind == "unknown":
            entries.append(ScanEntry("skip", "unsupported", "", path))
            continue
        if kind == "csv" and inspect_csv(path) is None:
            entries.append(ScanEntry("skip", "header-only", "", path))
            continue
        digest = None
        for other, other_digest in seen_sizes.get(size, []):
            digest = digest or _sha256(path)
            if other_digest == digest:
                entries.append(ScanEntry("skip", "duplicate-content", other.name, path))
                break
        else:
            table = table_name_from_path(path)
            if table in seen_tables:
                entries.append(ScanEntry("skip", "duplicate-table", seen_tables[table].name, path))
            else:
                seen_tables[table] = path
                seen_sizes.setdefault(size, []).append((path, digest or _sha256(path)))
                entries.append(ScanEntry("load", kind, table, path))
    return entries


def _looks_tabular(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            first, second = handle.readline(), handle.readline()
    except OSError:
        return False
    return any(sep in first for sep in (b",", b";", b"\t")) and bool(second.strip())


def load_folder(ctx: Context, folder: Path) -> Result:
    pump = exapump(ctx)
    if pump is None:
        raise Failed("exapump (the data-loading CLI) is not installed", remedy="exakit update")
    entries = scan_folder(folder)
    loadable = [e for e in entries if e.action == "load"]
    if not loadable:
        renames = [e for e in entries if e.kind == "extension"]
        if renames:
            raise Failed(f"{len(renames)} files in {folder} are tabular but named .txt/.tsv - exapump reads .csv and .parquet only. "
                         "Rename them to .csv to load them.")
        raise Failed(f"No CSV, Parquet or JSON files in {folder}.")
    schema = (ctx.env.get("EXAKIT_SCHEMA") or "STARTER_KIT").upper()
    if ctx.ui.interactive:
        answer = ctx.ui.prompt("Target schema (back to return)", schema)
        if answer.lower() in ("b", "back"):
            return Result(True, "cancelled")
        if not re.fullmatch(r"[A-Za-z0-9_]+", answer):
            raise BadInput(f"'{answer}' is not a schema name (letters, digits and underscores).")
        schema = answer.upper()
    _print_plan(ctx, entries)
    ensure_schema_for(ctx, pump, schema)
    tables = table_listing(pump.sql(profile_name(ctx), LISTING_SQL))
    receipts = Receipts.load(ctx.paths.cache / "load-receipts.tsv")
    inflight = ctx.paths.cache / "load-inflight"
    decisions = {e.path: _decide(e, schema, tables, receipts, inflight) for e in loadable}
    clashes = [e for e in loadable if decisions[e.path][0] == "clash"]
    on_existing = _clash_answer(ctx, schema, clashes, decisions)
    outcomes: list[tuple[str, ScanEntry, str, str, str]] = []
    loaded_count = 0
    for entry in loadable:
        decision, rows = decisions[entry.path]
        target = f"{schema}.{entry.table}"
        if decision == "done":
            outcomes.append(("skip", entry, entry.table, f"{rows} rows", "already loaded from this file - left as it is"))
            continue
        if decision == "clash" and on_existing == "skip":
            outcomes.append(("skip", entry, entry.table, "", "not loaded: the table already holds rows this kit did not put there"))
            continue
        if decision == "resume" or (decision == "clash" and on_existing == "replace"):
            pump.sql(profile_name(ctx), f"DROP TABLE IF EXISTS {target}")
            receipts.forget(target)
            ctx.log.line("RESET", target)
        inflight.parent.mkdir(parents=True, exist_ok=True)
        inflight.write_text(target)
        try:
            if entry.kind == "json":
                landed = load_json(ctx, pump, entry.path, target)
            else:
                info = inspect_csv(entry.path) if entry.kind == "csv" else None
                if not upload_with_recovery(ctx, pump, entry.path, target, delimiter=info.delimiter if info else None):
                    raise Failed(failure_reason(_log_tail(ctx), delimiter_name=info.delimiter_name if info else "comma"))
                landed = [target]
        except Failed as err:
            if decision != "clash" and rows in ("absent", "0"):
                after = table_listing(pump.sql(profile_name(ctx), LISTING_SQL)) or {}
                if after.get(target, 0) == 0 and rows == "absent":
                    pump.sql(profile_name(ctx), f"DROP TABLE IF EXISTS {target}")
            outcomes.append(("fail", entry, entry.table, "not loaded", err.message))
            inflight.unlink(missing_ok=True)
            continue
        inflight.unlink(missing_ok=True)
        loaded_count += 1
        outcomes.append(("ok", entry, ",".join(t.rpartition(".")[2] for t in landed), "@ROWS@", ""))
    after = table_listing(pump.sql(profile_name(ctx), LISTING_SQL)) or {}
    settled = []
    for mark, entry, table_text, rows_text, reason in outcomes:
        if rows_text == "@ROWS@":
            total = 0
            for name in table_text.split(","):
                count = after.get(f"{schema}.{name}", 0)
                receipts.record(f"{schema}.{name}", entry.path, count)
                total += count
            rows_text = f"{total} rows"
        settled.append((mark, entry, table_text, rows_text, reason))
    _print_outcomes(ctx, schema, settled)
    _record_last_load(ctx, "local_folder", schema, str(folder), files=loaded_count)
    skipped = sum(1 for s in settled if s[0] == "skip")
    failed = sum(1 for s in settled if s[0] == "fail")
    summary = f"{schema}: {loaded_count} file{'s' if loaded_count != 1 else ''} loaded"
    if skipped:
        summary += f", {skipped} already there and left alone"
    if failed:
        summary += f", {failed} not loaded"
        ctx.ui.warn(summary + " (each file's reason is against it above; full detail: exakit logs setup).")
        return Result(True, "partial", exit_code=1, data={"loaded": loaded_count, "failed": failed})
    if not loaded_count and skipped:
        ctx.ui.ok(f"{schema} already holds every file in that folder - nothing to load.")
    else:
        ctx.ui.ok(summary)
    return Result(True, "loaded", data={"loaded": loaded_count, "failed": 0})


def _decide(entry: ScanEntry, schema: str, tables: dict[str, int] | None, receipts: Receipts, inflight: Path) -> tuple[str, str]:
    """load | done | resume | clash, plus the rows the table holds now as text."""
    target = f"{schema}.{entry.table}"
    if tables is None:
        return "load", "unknown"
    rows = tables.get(target)
    if rows is None or rows == 0:
        return "load", "absent" if rows is None else "0"
    recorded = receipts.match(target, entry.path)
    if recorded is not None and recorded == rows:
        return "done", str(rows)
    try:
        if inflight.is_file() and inflight.read_text().strip() == target:
            return "resume", str(rows)
    except OSError:
        pass
    return "clash", str(rows)


def _clash_answer(ctx: Context, schema: str, clashes: list[ScanEntry], decisions) -> str:
    if not clashes:
        return "skip"
    answer = ctx.env.get("EXAKIT_ON_EXISTING", "").strip().lower()
    if answer in ("skip", "replace", "append"):
        return answer
    if answer:
        raise BadInput(f"EXAKIT_ON_EXISTING='{answer}' is not one of skip, replace, append.")
    ctx.ui.warn(f"{len(clashes)} table(s) in {schema} already holding rows this kit did not load:")
    for entry in clashes:
        ctx.ui.text(f"      - {entry.path.name} -> {decisions[entry.path][1]} rows already")
    if not ctx.ui.interactive:
        ctx.ui.info("Skipping those files. Re-run with EXAKIT_ON_EXISTING=replace or =append to decide otherwise.")
        return "skip"
    while True:
        reply = ctx.ui.prompt("Those files: (s)kip, (r)eplace what is there, or (a)ppend to it", "s").lower()
        if reply in ("s", "skip"):
            return "skip"
        if reply in ("r", "replace"):
            return "replace"
        if reply in ("a", "append"):
            return "append"


def _print_plan(ctx: Context, entries: list[ScanEntry]) -> None:
    for entry in entries:
        if entry.action == "load":
            ctx.ui.text(f"      - {entry.path.name} -> {entry.table}")
    for entry in entries:
        if entry.kind == "duplicate-content":
            ctx.ui.text(f"      ! {entry.path.name} skipped (identical to {entry.table})")
        elif entry.kind == "duplicate-table":
            ctx.ui.text(f"      ! {entry.path.name} skipped (same target table as {entry.table})")
    renames = sum(1 for e in entries if e.kind == "extension")
    if renames:
        ctx.ui.text(f"      ! {renames} files tabular but named .txt/.tsv - exapump reads .csv and .parquet only; rename to .csv to load")
    ignored = {k: sum(1 for e in entries if e.kind == k) for k in ("unsupported", "empty", "header-only")}
    if any(ignored.values()):
        ctx.ui.text(f"      ignored: {ignored['unsupported']} of other kinds, {ignored['empty']} empty, {ignored['header-only']} with a header and no rows")


def _print_outcomes(ctx: Context, schema: str, settled) -> None:
    marks = {"ok": "[ok]", "skip": "-", "fail": "[x]"}
    if ctx.ui.fancy:
        marks = {"ok": "✓", "skip": "•", "fail": "✗"}
    width = min(max([len(s[1].path.name) for s in settled] + [10]), 44)
    ctx.ui.text("")
    ctx.ui.text(f"     into {schema}")
    for mark, entry, table_text, rows_text, reason in settled:
        ctx.ui.text(f"     {marks[mark]:<4} {entry.path.name:<{width}} -> {table_text}  {rows_text}")
        if reason:
            ctx.ui.text(f"       {reason}")
    ctx.ui.text("")
