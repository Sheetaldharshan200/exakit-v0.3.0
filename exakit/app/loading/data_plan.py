"""``exakit data-load --dry-run``: what a load would do - folders to schemas, files to tables - with nothing loaded.

An agent shows this to the user before it loads anything. It needs no running database: the reserved words come from
the database when it answers and from the built-in list otherwise (the result says which), and they only ever add a
``_DATA`` suffix, so a name can differ between the two only for a word the database reserves and the list does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from exakit.domain.errors import ExakitError, Failed
from exakit.domain.result import Result

from .. import Context
from ..db.runtime_ops import exapump, is_running
from .data_files import Receipts, file_kind, file_problem, file_target
from .names import BUILT_IN_RESERVED

IGNORED = {"unsupported": "not a CSV, Parquet or JSON file", "empty": "empty", "header-only": "a header and no rows",
           "extension": "tabular but named .txt/.tsv - rename it to .csv", "duplicate-content": "identical to another file",
           "duplicate-table": "the same table name as another file"}


def plan(ctx: Context, path: Path | None, datasets: list[str]) -> Result:
    """The plan for a path, or for the bundled datasets when no path was named."""
    if path is None:
        return _datasets_plan(ctx, datasets)
    path = path.resolve()                       # "." and ".." name the folder they are, as the load does
    if not path.exists():
        raise Failed(f"No such file or folder: {path}")
    reserved, source = _reserved(ctx)
    return _folder_plan(ctx, path, reserved, source) if path.is_dir() else _file_plan(ctx, path, reserved, source)


def _reserved(ctx: Context) -> tuple[frozenset[str], str]:
    """The reserved words, and where they came from."""
    try:
        pump = exapump(ctx) if ctx.manifest_store.exists() else None
        if pump is not None and is_running(ctx):
            from .data_folder import reserved_words
            words = reserved_words(ctx, pump)
            return words, "database" if words != BUILT_IN_RESERVED else "built-in"
    except ExakitError as err:                  # no install, an unreadable record: the built-in list answers
        ctx.log.line("INFO", f"dry run without the database's reserved words: {err.message}")
    return BUILT_IN_RESERVED, "built-in"


def _folder_plan(ctx: Context, folder: Path, reserved: frozenset[str], source: str) -> Result:
    from .data_folder import _top_schema
    from .data_tree import scan_tree
    receipts = Receipts.load(ctx.paths.cache / "load-receipts.tsv")      # read only: who already holds a schema name
    plans = scan_tree(folder, top_schema=_top_schema(ctx, reserved), reserved=reserved, receipts=receipts)
    schemas = []
    for p in plans:
        files = [{"file": str(e.path), "table": e.table, "kind": e.kind} for e in p.loadable]
        ignored = [{"file": str(e.path), "reason": _reason(e.kind, e.table)} for e in p.entries if e.action != "load"]
        schemas.append({"folder": str(p.path), "schema": p.schema, "files": files, "ignored": ignored})
        ctx.ui.info(f"{_rel(p.path, folder)}/ -> {p.schema}  ({len(files)} file{'s' if len(files) != 1 else ''})")
        for f in files:
            ctx.ui.text(f"      - {Path(f['file']).name} -> {p.schema}.{f['table']}")
        for i in ignored:
            ctx.ui.text(f"      ! {Path(i['file']).name}: {i['reason']}")
    if not plans:
        ctx.ui.warn(f"Nothing in {folder} would load: no CSV, Parquet or JSON file with rows.")
    total = sum(len(s["files"]) for s in schemas)
    ctx.ui.ok(f"Dry run: {total} file{'s' if total != 1 else ''} into {len(schemas)} schema{'s' if len(schemas) != 1 else ''}; nothing was loaded. "
              f"Load it with: exakit data-load {folder}")
    return Result(True, "planned", remedy=f"exakit data-load {folder}",
                  data={"dry_run": True, "path": str(folder), "schemas": schemas, "reserved_words": source})


def _file_plan(ctx: Context, path: Path, reserved: frozenset[str], source: str) -> Result:
    refusal = file_problem(path)
    if refusal:
        raise Failed(refusal)                   # exactly what the load itself would refuse
    kind = file_kind(path)
    target = file_target(ctx, path, reserved)
    ctx.ui.ok(f"Dry run: {path.name} -> {target}{' (a nested file fans out to ' + target + '_* tables)' if kind == 'json' else ''}; "
              f"nothing was loaded. Load it with: exakit data-load {path}")
    return Result(True, "planned", remedy=f"exakit data-load {path}",
                  data={"dry_run": True, "path": str(path), "kind": kind, "target": target, "reserved_words": source})


def _datasets_plan(ctx: Context, datasets: list[str]) -> Result:
    from .data import bundled
    known = {d.id: d for d in bundled(ctx)}
    rows: list[dict[str, Any]] = [{"id": d, "schema": known[d].schema if d in known else None, "known": d in known} for d in datasets]
    for row in rows:
        ctx.ui.info(f"{row['id']} -> {row['schema']}" if row["known"] else f"{row['id']}: not a bundled dataset ({', '.join(known)})")
    ctx.ui.ok("Dry run: nothing was loaded. Load them with: exakit data-load (EXAKIT_DATASETS names them unattended)")
    return Result(True, "planned", remedy="exakit data-load", data={"dry_run": True, "datasets": rows, "available": list(known)})


def _reason(kind: str, other: str) -> str:
    text = IGNORED.get(kind, kind)
    return f"{text} ({other})" if kind.startswith("duplicate") and other else text


def _rel(path: Path, top: Path) -> str:
    return top.name if path == top else str(path.relative_to(top.parent))
