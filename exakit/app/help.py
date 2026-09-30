"""Help, catalog and their JSON surfaces, rendered from the help documents (setup/help/*.json).

This is the legacy renderer, moved out of a shell heredoc and given a
function signature. The documents are the single source of truth; the
screens and the JSON are two views of them. Hidden commands are omitted from
the screens and MARKED (never dropped) in the JSON.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

KNOWN_TOOLS = ("exakit", "exapump", "exasol", "dash-server", "exasol-json-tables", "exasol-mcp-server", "exasol-mcp-server-http")


def load_docs(help_dir: Path) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for path in sorted(help_dir.glob("*.json")) if help_dir.is_dir() else []:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            docs[path.stem] = doc
    return docs


def commands_of(doc: dict[str, Any], include_hidden: bool = False) -> list[dict[str, Any]]:
    entries = doc.get("commands", []) or []
    return entries if include_hidden else [e for e in entries if not e.get("hidden")]


def with_hidden_marked(doc: dict[str, Any]) -> dict[str, Any]:
    copy = dict(doc)
    copy["commands"] = [dict(e, hidden=bool(e.get("hidden"))) for e in commands_of(doc, include_hidden=True)]
    return copy


def catalog_rows(docs: dict[str, dict[str, Any]], include_hidden: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(docs):
        doc = docs[key]
        tool = "exakit" if key == "exakit" else key
        for entry in commands_of(doc, include_hidden=include_hidden):
            command = entry.get("command", "")
            parts = command.split()
            row_tool, row_command = tool, command
            if parts and parts[0] in ("exakit", "exapump", "exasol") and key != parts[0]:
                row_tool, row_command = parts[0], " ".join(parts[1:])
            rows.append({"tool": row_tool, "command": row_command, "options": entry.get("options", ""),
                         "description": entry.get("summary") or entry.get("description", ""),
                         "source": key, "hidden": bool(entry.get("hidden"))})
    at: dict[tuple[str, str], int] = {}
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (row["tool"], row["command"])
        if key not in at:
            at[key] = len(unique)
            unique.append(row)
            continue
        kept = unique[at[key]]
        if row["source"] == row["tool"] and kept["source"] != kept["tool"]:
            unique[at[key]] = row
    return unique


def _matches(row: dict[str, Any], needle: str) -> bool:
    return needle in " ".join([row["tool"], row["command"], row["options"], row["description"]]).lower()


def json_payload(docs: dict[str, dict[str, Any]], which: str) -> dict[str, Any]:
    rows = catalog_rows(docs, include_hidden=True)
    for row in rows:
        row["invocation"] = f"{row['tool']} {row['command']}".strip()
    if which in ("", "all"):
        return {"schema_version": 1, "search": None, "count": len(rows), "commands": rows,
                "documents": {k: with_hidden_marked(d) for k, d in docs.items()}}
    if which in docs:
        return with_hidden_marked(docs[which])
    hit = [r for r in rows if _matches(r, which.lower())]
    return {"schema_version": 1, "search": which, "count": len(hit), "commands": hit}


class HelpScreens:
    """The human screens. ``lines`` collects output; ``code`` is the exit code."""

    def __init__(self, docs: dict[str, dict[str, Any]], *, color: bool, width: int) -> None:
        self.docs = docs
        self.wrap = min(max(width, 40), 100)
        self.lines: list[str] = []
        if color:
            self.CY, self.CYB, self.DIM, self.B, self.GN, self.YL, self.R = (
                "\x1b[36m", "\x1b[1;36m", "\x1b[2m", "\x1b[1m", "\x1b[1;32m", "\x1b[33m", "\x1b[0m")
        else:
            self.CY = self.CYB = self.DIM = self.B = self.GN = self.YL = self.R = ""

    # --- primitives ---------------------------------------------------------------

    def out(self, text: str = "") -> None:
        self.lines.append(text)

    def para(self, text: str, indent: str = "  ", first: str | None = None) -> None:
        for line in textwrap.wrap(text, width=self.wrap - len(indent)) or [""]:
            self.out((first if first is not None else indent) + line)
            first = None

    def rule(self) -> None:
        self.out(f"  {self.CY}{'-' * (min(self.wrap, 72) - 2)}{self.R}")

    def header(self, title: str, subtitle: str = "") -> None:
        self.out()
        self.rule()
        sub = f"  {self.DIM}{subtitle}{self.R}" if subtitle else ""
        self.out(f"   {self.CYB}{title}{self.R}{sub}")
        self.rule()

    def section(self, title: str) -> None:
        self.out()
        self.out(f"  {self.B}{title}{self.R}")
        self.out()

    def kv(self, key: str, value: str, pad: int = 16) -> None:
        self.para(value, indent=" " * (4 + pad), first=f"    {self.GN}{key:<{pad}}{self.R}")

    def cmd_line(self, command: str, summary: str, pad: int = 22, indent: str = "    ") -> None:
        if len(command) <= pad and summary:
            self.para(summary, indent=" " * (len(indent) + pad + 1), first=f"{indent}{self.GN}{command:<{pad}}{self.R} ")
        else:
            self.out(f"{indent}{self.GN}{command}{self.R}")
            if summary:
                self.para(summary, indent=indent + "  ")

    def invocation(self, doc_id: str, entry: dict[str, Any]) -> str:
        command = (entry.get("command") or "").strip()
        parts = command.split()
        if parts and parts[0] in KNOWN_TOOLS:
            return command
        prefix = (self.docs.get(doc_id) or {}).get("invocation_prefix") or doc_id
        return f"{prefix} {command}".strip()

    def invocation_with_options(self, doc_id: str, entry: dict[str, Any]) -> str:
        label = self.invocation(doc_id, entry)
        return f"{label} {entry['options']}" if entry.get("options") else label

    # --- screens ------------------------------------------------------------------

    def overview(self) -> int:
        doc = self.docs.get("exakit")
        if not doc:
            self.out("No help data found. Reinstall the kit or run: exakit update")
            return 1
        self.header(doc.get("title", "exakit"), doc.get("tagline", ""))
        if doc.get("role"):
            self.out()
            self.para(doc["role"], indent="   ")
        if doc.get("quickstart"):
            self.section("Start here")
            for number, step in enumerate(doc["quickstart"], 1):
                self.out(f"    {self.B}{number}.{self.R} {step.get('step', '')}")
                if step.get("run"):
                    self.out(f"       {self.CY}{step['run']}{self.R}")
                if step.get("note"):
                    self.para(step["note"], indent=f"       {self.DIM}")
            self.out()
        by_name = {c.get("command"): c for c in commands_of(doc)}
        seen: set[str] = set()
        for group in doc.get("groups", []):
            rows = [by_name[n] for n in group.get("commands", []) if n in by_name and n not in seen]
            seen.update(n for n in group.get("commands", []) if n in by_name)
            if not rows:
                continue
            self.section(group.get("title", ""))
            for entry in rows:
                self.cmd_line(self.invocation("exakit", entry), entry.get("summary", ""), pad=24)
        self.out()
        self.out()
        return 0

    def all_commands(self) -> int:
        doc = self.docs.get("exakit")
        if not doc:
            return 1
        self.header("exakit - every command", doc.get("tagline", ""))
        by_name = {c.get("command"): c for c in commands_of(doc)}
        seen: set[str] = set()
        for group in doc.get("groups", []):
            self.section(group.get("title", ""))
            for name in group.get("commands", []):
                entry = by_name.get(name)
                if not entry or name in seen:
                    continue
                seen.add(name)
                self.cmd_line(self.invocation_with_options("exakit", entry), entry.get("summary", ""), pad=30)
        rest = [c for c in commands_of(doc) if c.get("command") not in seen]
        if rest:
            self.section("Other")
            for entry in rest:
                self.cmd_line(self.invocation_with_options("exakit", entry), entry.get("summary", ""), pad=30)
        others = [key for key in sorted(self.docs) if key != "exakit"]
        if others:
            self.section("Components")
            for key in others:
                sub = self.docs[key]
                self.out(f"    {self.B}{key}{self.R}  {self.DIM}{sub.get('tagline', '')}{self.R}")
                for entry in commands_of(sub):
                    self.cmd_line(self.invocation_with_options(key, entry),
                                  entry.get("summary") or entry.get("description", ""), pad=34, indent="      ")
                self.out()
        self.out()
        self.para("Detail for one command: exakit <command> --help", indent=f"  {self.DIM}")
        self.out()
        return 0

    def component(self, key: str) -> int:
        doc = self.docs.get(key)
        if not doc:
            self.out(f"  No help document for '{key}'.")
            self.out(f"  Known: {', '.join(sorted(self.docs))}")
            return 1
        self.header(doc.get("title", key), doc.get("tagline", ""))
        self.out()
        self.para(doc.get("role", ""), indent="   ")
        facts = [("Repository", doc.get("repo")), ("Package", doc.get("package")), ("Binary", doc.get("binary")),
                 ("Runs via", doc.get("runs_via")), ("Image", doc.get("image")), ("Config", doc.get("config")),
                 ("Profile", doc.get("profile")), ("Venv", doc.get("venv")), ("Python", doc.get("python")),
                 ("URL", doc.get("url")), ("Control plane", doc.get("control_plane")), ("DSN", doc.get("dsn")),
                 ("Admin user", doc.get("admin_user")), ("DB user", doc.get("db_user")),
                 ("Deployment", doc.get("deployment_dir")), ("Platforms", doc.get("platforms")),
                 ("Requires", doc.get("requires")), ("Installed by", doc.get("installed_by")), ("Docs", doc.get("docs"))]
        facts = [(k, v) for k, v in facts if v]
        if facts:
            self.section("At a glance")
            for name, value in facts:
                self.kv(name, str(value))
        if doc.get("warning"):
            self.section("Important")
            self.para(doc["warning"], indent="    ", first=f"    {self.YL}!{self.R} ")
        if doc.get("boundary"):
            self.section("The read-only boundary")
            self.para(doc["boundary"], indent="    ")
        if doc.get("clients"):
            self.section("Supported clients")
            self.para(", ".join(doc["clients"]), indent="    ")
        if doc.get("quickstart"):
            self.section("How to start")
            for number, step in enumerate(doc["quickstart"], 1):
                self.out(f"    {self.B}{number}.{self.R} {step.get('step', '')}")
                if step.get("run"):
                    self.out(f"       {self.CY}{step['run']}{self.R}")
                if step.get("note"):
                    self.para(step["note"], indent="       ")
        if commands_of(doc):
            self.section("Commands")
            for entry in commands_of(doc):
                self.cmd_line(self.invocation_with_options(key, entry),
                              entry.get("summary") or entry.get("description", ""), pad=34)
        if doc.get("snippets"):
            self.section("Examples")
            for index, snippet in enumerate(doc["snippets"]):
                if index:
                    self.out()
                self.out(f"    {self.B}{snippet.get('title', '')}{self.R}")
                for line in snippet.get("code", "").split("\n"):
                    self.out(f"      {self.CY}{line}{self.R}")
        if doc.get("environment"):
            self.section("Environment")
            for item in doc["environment"]:
                self.kv(item.get("name", ""), item.get("effect", ""), pad=26)
        if doc.get("notes"):
            self.section("Good to know")
            for note in doc["notes"]:
                self.para(note, indent="      ", first=f"    {self.DIM}-{self.R} ")
        if doc.get("troubleshooting"):
            self.section("If something goes wrong")
            for item in doc["troubleshooting"]:
                self.out(f"    {self.B}{item.get('symptom', '')}{self.R}")
                self.para(item.get("remedy", ""), indent="      ")
        if doc.get("see_also"):
            self.section("See also")
            self.para(", ".join(doc["see_also"]), indent="    ")
        self.out()
        return 0

    def _find(self, doc: dict[str, Any], name: str) -> list[dict[str, Any]]:
        name = name.strip().lower()
        exact, prefix = [], []
        for entry in commands_of(doc, include_hidden=True):
            key = entry.get("command", "").lower()
            if key == name:
                exact.append(entry)
            elif key.startswith(name + " ") or name.startswith(key + " "):
                prefix.append(entry)
        return exact or prefix

    def _detail(self, entry: dict[str, Any], prefix: str = "") -> None:
        label = f"{prefix} {entry.get('command', '')}".strip()
        opts = entry.get("options", "")
        self.out()
        self.out(f"  {self.B}{label}{' ' + opts if opts else ''}{self.R}")
        self.out()
        self.para(entry.get("description") or entry.get("summary", ""), indent="    ")
        if entry.get("warning"):
            self.out()
            self.para(entry["warning"], indent="    ", first=f"    {self.YL}!{self.R} ")
        if entry.get("exit_codes"):
            self.out()
            self.out(f"    {self.DIM}Exit codes{self.R}")
            for code in sorted(entry["exit_codes"], key=lambda c: int(c)):
                self.out(f"      {self.GN}{code}{self.R}  {entry['exit_codes'][code]}")
        if entry.get("environment"):
            self.out()
            self.out(f"    {self.DIM}Environment{self.R}")
            for line in entry["environment"]:
                self.para(line, indent="        ", first="      ")
        if entry.get("examples"):
            self.out()
            self.out(f"    {self.DIM}Examples{self.R}")
            for example in entry["examples"]:
                self.out(f"      {self.CY}{example}{self.R}")
        self.out()

    def command(self, name: str) -> int:
        doc = self.docs.get("exakit")
        matches = self._find(doc, name) if doc else []
        if matches:
            for entry in matches:
                self._detail(entry, prefix="exakit")
            return 0
        for key in sorted(self.docs):
            if key == "exakit":
                continue
            found = self._find(self.docs[key], name)
            if found:
                for entry in found:
                    self._detail(entry)
                self.out(f"  {self.DIM}Full reference: exakit {key} --help{self.R}")
                self.out()
                return 0
        if name in self.docs:
            return self.component(name)
        self.out()
        self.out(f"  No help entry for '{name}'.")
        self.out(f"  Try: exakit catalog {name}   or   exakit help --all")
        self.out()
        return 1

    def catalog(self, search: str) -> int:
        rows = catalog_rows(self.docs)
        if search:
            rows = [r for r in rows if _matches(r, search.lower())]
        self.header("command catalog", f'results for "{search}"' if search else "exakit - exapump - exasol - components")
        if not rows:
            self.out()
            self.out(f'  {self.DIM}No commands match "{search}".{self.R}  Try: exakit catalog mcp')
            self.out()
            return 1
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["tool"], []).append(row)
        tools = sorted(grouped)
        if "exakit" in tools:
            tools.remove("exakit")
            tools.insert(0, "exakit")
        for tool in tools:
            self.section(tool)
            entries = grouped[tool]
            pad = min(max([len(r["command"]) for r in entries] + [12]), 30)
            for row in sorted(entries, key=lambda r: r["command"]):
                self.cmd_line(row["command"], row["description"], pad=pad)
        self.out()
        self.out()
        return 0


def render(docs: dict[str, dict[str, Any]], mode: str, arg: str, *, color: bool, width: int) -> tuple[str, int]:
    """One of overview | all | component | command | catalog -> (text, exit code)."""
    screens = HelpScreens(docs, color=color, width=width)
    code = {"overview": screens.overview, "all": screens.all_commands}.get(mode, None)
    if code is not None:
        rc = code()
    elif mode == "component":
        rc = screens.component(arg)
    elif mode == "command":
        rc = screens.command(arg)
    elif mode == "catalog":
        rc = screens.catalog(arg)
    else:
        rc = screens.overview()
    return "\n".join(screens.lines) + "\n", rc
