"""A folder tree to load: every folder holding loadable files becomes a schema, and the user picks the folders.

The name of a folder's schema depends on its own path under the folder that was named and on nothing else, so a
re-run - with folders added or removed beside it - loads into the same schema again:

    my-data/                 MY_DATA          (EXAKIT_SCHEMA, or the answer to the prompt, replaces it)
    my-data/north/           NORTH
    my-data/north/archive/   NORTH_ARCHIVE
    my-data/south/archive/   SOUTH_ARCHIVE

Two folders whose paths fold to one name (north/archive and north_archive) are told apart in walk order: the first keeps
the name, the next carries the top folder's name in front, and after that a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from exakit.domain.errors import BadInput
from exakit.ui.widgets import Option

from .. import Context
from .data_folder import ScanEntry, scan_folder
from .names import BUILT_IN_RESERVED, fit, identifier, problem

LEAD = "DATA"                   # in front of a name that would start with a digit


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


def schema_name(folder: Path, top: Path | None = None, reserved: frozenset[str] = BUILT_IN_RESERVED) -> str:
    """The schema for ``folder``: its name for the top folder, its path under ``top`` joined by underscores below it."""
    if top is None or folder == top:
        return identifier(folder.name, lead=LEAD, reserved=reserved, key=str(folder))
    relative = folder.relative_to(top).parts
    return identifier("_".join(relative), lead=LEAD, reserved=reserved, key="/".join(relative))


def scan_tree(folder: Path, *, top_schema: str | None = None, reserved: frozenset[str] = BUILT_IN_RESERVED) -> list[FolderPlan]:
    """The folder and every subfolder under it that holds loadable files, top down, each with its own schema; hidden folders are skipped."""
    plans: list[FolderPlan] = []
    _walk(folder, folder, 0, plans, reserved)
    for plan in plans:
        if top_schema and plan.path == folder:
            plan.schema = top_schema
    _keep_apart(plans, folder, reserved)
    return plans


def _walk(top: Path, folder: Path, depth: int, plans: list[FolderPlan], reserved: frozenset[str]) -> None:
    entries = scan_folder(folder, reserved)
    if any(e.action == "load" for e in entries):
        plans.append(FolderPlan(folder, depth, schema_name(folder, top, reserved), entries))
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".") and not p.is_symlink()):
        _walk(top, sub, depth + 1, plans, reserved)


def _keep_apart(plans: list[FolderPlan], top: Path, reserved: frozenset[str]) -> None:
    """No two folders share a schema: the first keeps it, the next gets the top folder's name in front, then a number."""
    taken: set[str] = set()
    prefix = identifier(top.name, lead=LEAD, reserved=reserved)
    for plan in plans:
        name, number = plan.schema, 2
        if name in taken and plan.path != top:
            name = fit(f"{prefix}_{plan.schema}", str(plan.path))
        while name in taken:
            name = fit(f"{plan.schema}_{number}", f"{plan.path}#{number}")
            number += 1
        plan.schema = name
        taken.add(name)


def choose_plans(ctx: Context, plans: list[FolderPlan], *, reserved: frozenset[str] = BUILT_IN_RESERVED,
                 top_given: bool = False) -> list[FolderPlan] | None:
    """Which folders load. One folder: the schema may be changed at the prompt; a tree: a tick list, every folder ticked. None = back."""
    if len(plans) == 1:
        if top_given or not ctx.ui.interactive:
            return plans
        answer = ctx.ui.prompt("Target schema (back to return)", plans[0].schema).strip()
        if answer.lower() in ("b", "back"):
            return None
        reason = problem(answer, reserved)
        if reason:
            raise BadInput(f"'{answer}' cannot be a schema name: {reason}.")
        plans[0].schema = answer.upper()
        return plans
    if not ctx.ui.interactive:
        return plans
    options = [Option(str(p.path), f"{'  ' * p.depth}{p.path.name}/", f"-> {p.schema}  ({len(p.loadable)} file{'s' if len(p.loadable) != 1 else ''})")
               for p in plans]
    chosen = ctx.ui.checkboxes("Folders to load - each becomes a schema of its own", options, defaults=[o.id for o in options])
    picked = [p for p in plans if str(p.path) in set(chosen)]
    return picked or None
