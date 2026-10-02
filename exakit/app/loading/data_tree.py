"""A folder tree to load: every folder holding loadable files becomes a schema named after it, and the user picks the folders."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from exakit.domain.errors import BadInput
from exakit.ui.widgets import Option

from .. import Context
from .data_folder import ScanEntry, scan_folder


@dataclass
class FolderPlan:
    path: Path
    depth: int
    schema: str
    entries: list[ScanEntry] = field(default_factory=list)

    @property
    def loadable(self) -> list[ScanEntry]:
        """The files that will load."""
        return [e for e in self.entries if e.action == "load"]


def schema_name(folder: Path) -> str:
    """The schema a folder maps to: its name upper-cased, anything but letters, digits and underscores folded to one underscore."""
    text = re.sub(r"[^A-Za-z0-9_]+", "_", folder.name).strip("_").upper() or "DATA"
    return f"_{text}" if text[0].isdigit() else text


def scan_tree(folder: Path) -> list[FolderPlan]:
    """The folder and every subfolder under it that holds loadable files, top down, each with its schema; hidden folders are skipped."""
    plans: list[FolderPlan] = []
    _walk(folder, 0, plans)
    seen: set[str] = set()
    for plan in plans:                     # two folders with one name: the deeper one carries its parent's name as a prefix
        if plan.schema in seen and plan.depth:
            plan.schema = f"{schema_name(plan.path.parent)}_{plan.schema}"
        seen.add(plan.schema)
    return plans


def _walk(folder: Path, depth: int, plans: list[FolderPlan]) -> None:
    entries = scan_folder(folder)
    if any(e.action == "load" for e in entries):
        plans.append(FolderPlan(folder, depth, schema_name(folder), entries))
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")):
        _walk(sub, depth + 1, plans)


def choose_plans(ctx: Context, plans: list[FolderPlan], top: Path) -> list[FolderPlan] | None:
    """Which folders load, into which schemas. EXAKIT_SCHEMA names the top folder's schema; one folder is asked as before; a tree is a tick list. None = back."""
    override = (ctx.env.get("EXAKIT_SCHEMA") or "").strip()
    for plan in plans:
        if override and plan.path == top:
            plan.schema = override.upper()
    if len(plans) == 1:
        if override or not ctx.ui.interactive:
            return plans
        answer = ctx.ui.prompt("Target schema (back to return)", plans[0].schema)
        if answer.lower() in ("b", "back"):
            return None
        if not re.fullmatch(r"[A-Za-z0-9_]+", answer):
            raise BadInput(f"'{answer}' is not a schema name (letters, digits and underscores).")
        plans[0].schema = answer.upper()
        return plans
    if not ctx.ui.interactive:
        return plans
    options = [Option(str(p.path), f"{'  ' * p.depth}{p.path.name}/", f"-> {p.schema}  ({len(p.loadable)} file{'s' if len(p.loadable) != 1 else ''})")
               for p in plans]
    chosen = ctx.ui.checkboxes("Folders to load - each becomes a schema named after it", options, defaults=[o.id for o in options])
    picked = [p for p in plans if str(p.path) in set(chosen)]
    return picked or None
