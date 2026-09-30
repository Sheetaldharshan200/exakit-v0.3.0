"""The catalog: what the kit is made of, as data.

Three kinds of document, all under ``catalog/`` in the kit copy:

    components/<id>.json      the fixed components every install has
    addons/<id>/addon.json    optional add-ons (the marketplace)
    personas/<id>.json        named bundles of the install's optional choices

Plus a user's own personas under ``$EXAKIT_HOME/personas/``, which shadow the
shipped ones by id. The directory is the registry: nothing in code names a
component, an add-on or a persona. Validation returns a list of problems so a
shipped file that is wrong fails CI, and a user's file that is wrong is
skipped with one warning, never fatal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import BadInput
from .ids import is_token, parse_client_selection
from .platform import ARCH_NAMES, OS_NAMES

COMPONENT_KINDS = ("runtime", "binary", "python-tool", "python-venv", "skills", "helper")
ADDON_KINDS = ("python-venv", "binary", "host-extension", "custom")
SOURCE_TYPES = ("github_release", "github_tag", "pypi", "kit")
PLATFORM_KEYS = tuple(f"{o}-{a}" for o in OS_NAMES for a in ARCH_NAMES)

Problems = list[str]


# --- helpers ----------------------------------------------------------------------


def _is_str(value: Any, *, max_len: int | None = None, ascii_only: bool = True) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if ascii_only and not value.isascii():
        return False
    return max_len is None or len(value) <= max_len


def _check_id(doc: dict[str, Any], expected_id: str | None, problems: Problems) -> None:
    cid = doc.get("id")
    if not isinstance(cid, str) or not is_token(cid) or "_" in cid:
        problems.append("id must be lowercase letters, digits and dashes")
    elif expected_id is not None and cid != expected_id:
        problems.append(f"id '{cid}' does not match the file name '{expected_id}'")


def _check_schema(doc: Any, problems: Problems) -> bool:
    if not isinstance(doc, dict):
        problems.append("not a JSON object")
        return False
    if doc.get("schema_version") != 1:
        announced = doc.get("schema_version")
        if isinstance(announced, int) and announced > 1:
            problems.append(f"schema_version {announced} needs a newer kit (exakit update)")
        else:
            problems.append("schema_version must be 1")
        return False
    return True


def _check_source(source: Any, problems: Problems) -> None:
    if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES:
        problems.append(f"source.type must be one of {', '.join(SOURCE_TYPES)}")
        return
    kind = source["type"]
    if kind in ("github_release", "github_tag") and not _is_str(source.get("repo")):
        problems.append("source.repo is required for a GitHub source")
    if kind == "pypi" and not _is_str(source.get("package")):
        problems.append("source.package is required for a PyPI source")


def _check_id_list(doc: dict[str, Any], key: str, problems: Problems, *, allow_words: tuple[str, ...] = ()) -> None:
    value = doc.get(key)
    if isinstance(value, str) and value in allow_words:
        return
    if not isinstance(value, list) or not all(isinstance(v, str) and is_token(v) for v in value):
        joined = '", "'.join(allow_words)
        words = f' or one of "{joined}"' if allow_words else ""
        problems.append(f"{key} must be a list of ids{words}")


# --- components -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Component:
    id: str
    title: str
    kind: str
    source: dict[str, Any]
    install_order: int
    step_id: str | None
    fallback_version: str | None
    requires: tuple[str, ...]
    help: str | None
    manifest_key: str

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> Component:
        return cls(
            id=doc["id"], title=doc["title"], kind=doc["kind"], source=dict(doc.get("source") or {"type": "kit"}),
            install_order=int(doc.get("install_order", 100)), step_id=doc.get("step_id"),
            fallback_version=doc.get("fallback_version"), requires=tuple(doc.get("requires") or ()),
            help=doc.get("help"), manifest_key=doc.get("manifest_key") or doc["id"].replace("-", "_"),
        )


def validate_component(doc: Any, *, expected_id: str | None = None) -> Problems:
    problems: Problems = []
    if not _check_schema(doc, problems):
        return problems
    _check_id(doc, expected_id, problems)
    if not _is_str(doc.get("title"), max_len=60):
        problems.append("title must be a non-empty ASCII string of at most 60 characters")
    if doc.get("kind") not in COMPONENT_KINDS:
        problems.append(f"kind must be one of {', '.join(COMPONENT_KINDS)}")
    if "source" in doc:
        _check_source(doc["source"], problems)
    if not isinstance(doc.get("install_order", 100), int):
        problems.append("install_order must be an integer")
    for key in ("step_id", "fallback_version", "help", "manifest_key"):
        if key in doc and not _is_str(doc[key]):
            problems.append(f"{key} must be a non-empty string")
    if "requires" in doc:
        _check_id_list(doc, "requires", problems)
    return problems


# --- add-ons ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Addon:
    id: str
    title: str
    kind: str
    source: dict[str, Any]
    platforms: tuple[str, ...]          # empty = every platform
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    service: dict[str, Any] | None
    launcher: str | None
    skill: str | None
    help: str | None
    fallback_version: str | None
    manifest_key: str
    directory: Path | None = field(default=None, compare=False)

    @classmethod
    def from_doc(cls, doc: dict[str, Any], directory: Path | None = None) -> Addon:
        return cls(
            id=doc["id"], title=doc["title"], kind=doc["kind"], source=dict(doc["source"]),
            platforms=tuple(doc.get("platforms") or ()), requires=tuple(doc.get("requires") or ()),
            provides=tuple(doc.get("provides") or ()), service=doc.get("service"),
            launcher=doc.get("launcher"), skill=doc.get("skill"), help=doc.get("help"),
            fallback_version=doc.get("fallback_version"),
            manifest_key=doc.get("manifest_key") or doc["id"].replace("-", "_"), directory=directory,
        )

    def supports(self, platform_key: str) -> bool:
        return not self.platforms or platform_key in self.platforms


def validate_addon(doc: Any, *, expected_id: str | None = None) -> Problems:
    problems: Problems = []
    if not _check_schema(doc, problems):
        return problems
    _check_id(doc, expected_id, problems)
    if not _is_str(doc.get("title"), max_len=60):
        problems.append("title must be a non-empty ASCII string of at most 60 characters")
    if doc.get("kind") not in ADDON_KINDS:
        problems.append(f"kind must be one of {', '.join(ADDON_KINDS)}")
    _check_source(doc.get("source"), problems)
    platforms = doc.get("platforms", [])
    if not isinstance(platforms, list) or any(p not in PLATFORM_KEYS for p in platforms):
        problems.append(f"platforms must list keys from {', '.join(PLATFORM_KEYS)}")
    for key in ("requires", "provides"):
        if key in doc:
            _check_id_list(doc, key, problems)
    service = doc.get("service")
    if service is not None and (not isinstance(service, dict) or not isinstance(service.get("port", 0), int)):
        problems.append("service must be an object with an integer port")
    for key in ("launcher", "skill", "help", "fallback_version", "manifest_key"):
        if key in doc and not _is_str(doc[key]):
            problems.append(f"{key} must be a non-empty string")
    return problems


# --- personas -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Persona:
    id: str
    title: str
    summary: str
    datasets: str | tuple[str, ...]      # "all" | "none" | ids
    mcp_clients: str | tuple[str, ...]   # "all" | "skip" | client ids
    addons: str | tuple[str, ...]        # "all" | "none" | ids
    skills: str
    source: str                          # kit | user
    path: Path | None = field(default=None, compare=False)

    @classmethod
    def from_doc(cls, doc: dict[str, Any], *, source: str, path: Path | None = None) -> Persona:
        def norm(value: Any) -> str | tuple[str, ...]:
            return value if isinstance(value, str) else tuple(value)
        return cls(
            id=doc["id"], title=doc["title"], summary=doc["summary"], datasets=norm(doc["datasets"]),
            mcp_clients=norm(doc["mcp_clients"]), addons=norm(doc["addons"]), skills=doc["skills"],
            source=source, path=path,
        )

    def to_dict(self) -> dict[str, Any]:
        def raw(value: str | tuple[str, ...]) -> Any:
            return value if isinstance(value, str) else list(value)
        return {
            "schema_version": 1, "id": self.id, "title": self.title, "summary": self.summary,
            "datasets": raw(self.datasets), "mcp_clients": raw(self.mcp_clients),
            "addons": raw(self.addons), "skills": self.skills,
        }


def validate_persona(
    doc: Any,
    *,
    expected_id: str | None = None,
    known_datasets: Iterable[str] | None = None,
    known_addons: Iterable[str] | None = None,
) -> Problems:
    """Schema 1. Cross-checks against the known ids only when they are given."""
    problems: Problems = []
    if not _check_schema(doc, problems):
        return problems
    _check_id(doc, expected_id, problems)
    if not _is_str(doc.get("title"), max_len=40):
        problems.append("title must be a non-empty ASCII string of at most 40 characters")
    if not _is_str(doc.get("summary"), max_len=120):
        problems.append("summary must be a non-empty ASCII string of at most 120 characters")
    _check_choice(doc, "datasets", ("all", "none"), known_datasets, "dataset", problems)
    _check_clients(doc, problems)
    _check_choice(doc, "addons", ("all", "none"), known_addons, "add-on", problems)
    if doc.get("skills") != "all":
        problems.append('skills must be "all" in schema 1')
    return problems


def _check_choice(doc: dict[str, Any], key: str, words: tuple[str, ...], known: Iterable[str] | None,
                  noun: str, problems: Problems) -> None:
    value = doc.get(key)
    if isinstance(value, str):
        if value not in words:
            problems.append(f'{key} must be "{words[0]}", "{words[1]}" or a list of {noun} ids')
        return
    if not isinstance(value, list) or not value:
        problems.append(f'{key} must be "{words[0]}", "{words[1]}" or a non-empty list of {noun} ids')
        return
    known_set = set(known) if known is not None else None
    for item in value:
        if not isinstance(item, str) or not is_token(item):
            problems.append(f"{key}: '{item}' is not a valid id")
        elif known_set is not None and item not in known_set:
            problems.append(f"{key}: '{item}' is not a {noun} this kit knows")


def _check_clients(doc: dict[str, Any], problems: Problems) -> None:
    value = doc.get("mcp_clients")
    if isinstance(value, str):
        if value not in ("all", "skip"):
            problems.append('mcp_clients must be "all", "skip" or a list of client names')
        return
    if not isinstance(value, list) or not value:
        problems.append('mcp_clients must be "all", "skip" or a non-empty list of client names')
        return
    for item in value:
        if not isinstance(item, str) or not item.replace("_", "").isalpha() or item.isdigit():
            problems.append(f"mcp_clients: '{item}' is not a client name (names, never numbers)")
            continue
        try:
            parse_client_selection(item)
        except BadInput:
            problems.append(f"mcp_clients: '{item}' is not one EXAKIT_MCP_CLIENTS accepts")


# --- the catalog ----------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Catalog:
    """Everything the kit knows about, loaded once per command."""

    def __init__(self, components: dict[str, Component], addons: dict[str, Addon], personas: dict[str, Persona]) -> None:
        self._components = components
        self._addons = addons
        self._personas = personas

    @classmethod
    def load(cls, kit_root: Path, user_root: Path | None, *, warn: Callable[[str], None]) -> Catalog:
        """Read the kit's catalog and the user's personas. A bad file is skipped with one warning."""
        components = _load_components(kit_root / "catalog" / "components", warn)
        addons = _load_addons(kit_root / "catalog" / "addons", warn)
        personas: dict[str, Persona] = {}
        dirs = [(user_root, "user")] if user_root else []
        dirs.append((kit_root / "catalog" / "personas", "kit"))
        for directory, source in dirs:
            for persona in _load_personas(directory, source, set(addons), warn):
                personas.setdefault(persona.id, persona)   # user first, so the user's copy wins
        return cls(components, addons, dict(sorted(personas.items())))

    # --- lookups; unknown ids are BadInput naming the known ones ----------------------

    def component(self, cid: str) -> Component:
        return self._lookup(self._components, cid, "component")

    def addon(self, aid: str) -> Addon:
        return self._lookup(self._addons, aid, "marketplace add-on")

    def persona(self, pid: str) -> Persona:
        return self._lookup(self._personas, pid, "persona")

    def has_addon(self, aid: str) -> bool:
        return aid in self._addons

    def component_ids(self) -> list[str]:
        return [c.id for c in sorted(self._components.values(), key=lambda c: (c.install_order, c.id))]

    def addon_ids(self) -> list[str]:
        return sorted(self._addons)

    def persona_ids(self) -> list[str]:
        return list(self._personas)

    def personas(self) -> list[Persona]:
        return list(self._personas.values())

    def addons(self) -> list[Addon]:
        return [self._addons[a] for a in self.addon_ids()]

    @staticmethod
    def _lookup(table: dict[str, Any], key: str, noun: str) -> Any:
        if key in table:
            return table[key]
        known = " ".join(sorted(table)) or "none"
        raise BadInput(f"Unknown {noun} '{key}' (known: {known}).")


def _load_components(directory: Path, warn: Callable[[str], None]) -> dict[str, Component]:
    result: dict[str, Component] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        doc = _read_json(path)
        problems = validate_component(doc, expected_id=path.stem)
        if problems:
            warn(f"Ignoring component file {path}: {problems[0]}")
            continue
        result[path.stem] = Component.from_doc(doc)
    return result


def _load_addons(directory: Path, warn: Callable[[str], None]) -> dict[str, Addon]:
    result: dict[str, Addon] = {}
    for path in sorted(directory.glob("*/addon.json")) if directory.is_dir() else []:
        doc = _read_json(path)
        problems = validate_addon(doc, expected_id=path.parent.name)
        if problems:
            warn(f"Ignoring add-on file {path}: {problems[0]}")
            continue
        result[path.parent.name] = Addon.from_doc(doc, directory=path.parent)
    return result


def _load_personas(directory: Path, source: str, known_addons: set[str], warn: Callable[[str], None]) -> list[Persona]:
    result: list[Persona] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        doc = _read_json(path)
        problems = validate_persona(doc, expected_id=path.stem, known_addons=known_addons or None)
        if problems:
            warn(f"Ignoring persona file {path}: {problems[0]}")
            continue
        result.append(Persona.from_doc(doc, source=source, path=path))
    return result
