#!/usr/bin/env python3
"""Every surface that names an exakit command agrees with the CLI.

An agent believes what it reads: a command a skill names that the CLI does not answer, a read-only set that differs from
the allowlist, a help contract that leaves one command out - each is a wrong turn. This module is the one place that
holds them together; tools/release_check.py (check `commands`) and tests/unit/test_command_sync.py both run it.

    python3 tools/command_sync.py      # the findings, one per line; exit 1 when there is any
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EFFECTS = ("read", "write", "destructive")
# Markdown and JSON the agents read; docs/ and CHANGELOG.md are history and design talk, not instructions.
PROSE = ("AGENTS.md", "CLAUDE.md", "README.md", "QUICKSTART.md", "MARKETPLACE.md")
PROSE_GLOBS = ("skills/**/*.md", "quickstarts/**/*.md", "data/**/*.md", "mcp/README.md")
# English words that follow "exakit" in a code string without being a command ("exakit process holds the lock").
NOT_COMMANDS = frozenset({"process", "updated", "first", "command", "commands", "helper", "itself", "home", "is", "has", "loads",
                          "resolves", "launcher", "layer", "import", "and", "or", "the", "to", "in", "on", "for", "from", "with",
                          "can", "kit", "cli", "version", "dashboard", "runtime", "as", "do", "all"})
_MD_CODE = re.compile(r"`(?:[^`]*?\s)?exakit ([a-z][a-z0-9-]*[a-z0-9])")
_CODE_LINE = re.compile(r"^\s*(?:\$\s*)?(?:[A-Z_]+=\S+\s+)*(?:~/\.local/bin/)?exakit ([a-z][a-z0-9-]*[a-z0-9])")
_IN_STRING = re.compile(r"(?:^|[\s:(`'\"])exakit ([a-z][a-z0-9-]*[a-z0-9])\b")


def help_doc() -> dict:
    """help/exakit.json."""
    return json.loads((REPO / "help" / "exakit.json").read_text(encoding="utf-8"))


def valid_words() -> set[str]:
    """What may follow `exakit `: a command, an alias, a help page id (a bare id renders its page)."""
    from exakit.cli.main import HANDLERS
    return set(HANDLERS) | {p.stem for p in (REPO / "help").glob("*.json")}


def surface_findings() -> list[str]:
    """The CLI's table, the help contract, the read-only set and the allowlist agree; every entry says its effect."""
    from exakit.app.addons.skills import READONLY_COMMANDS as ALLOWED, allowlist_entries
    from exakit.cli.main import ALIASES, HANDLERS, READONLY_COMMANDS
    entries = {c["command"]: c for c in help_doc()["commands"]}
    handled = {name for name in HANDLERS if name not in ALIASES}
    found = [f"documented but no handler: {c}" for c in sorted(set(entries) - handled)]
    found += [f"handler without a help entry: {c}" for c in sorted(handled - set(entries))]
    for name, entry in entries.items():
        if entry.get("effect") not in EFFECTS:
            found.append(f"help entry '{name}' has no effect (one of {', '.join(EFFECTS)})")
        if not isinstance(entry.get("prompt_free"), bool):
            found.append(f"help entry '{name}' has no prompt_free (true or false)")
        if entry.get("prompt_free") and entry.get("effect") == "destructive":
            found.append(f"help entry '{name}' is destructive and prompt_free")
    reads = {n for n, e in entries.items() if (e.get("effect") == "read" and not e.get("interactive_only")) or e.get("read_forms")}
    if set(READONLY_COMMANDS) != reads:
        found.append(f"cli READONLY_COMMANDS {sorted(READONLY_COMMANDS)} differ from the read commands of the help contract {sorted(reads)}")
    free = {n for n, e in entries.items() if e.get("prompt_free")}
    if set(ALLOWED) | {"skills"} != free:
        found.append(f"the Claude Code allowlist {sorted(set(ALLOWED) | {'skills'})} differs from the prompt_free commands {sorted(free)}")
    allow, deny = allowlist_entries()
    found += _guide_findings(allow, deny)
    return found


def _guide_findings(allow: list[str], deny: list[str]) -> list[str]:
    """skills/reducing-agent-prompts.md shows exactly what the kit writes, and says how many."""
    text = (REPO / "skills" / "reducing-agent-prompts.md").read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not match:
        return ["skills/reducing-agent-prompts.md has no JSON block for Claude Code"]
    perms = json.loads(match.group(1)).get("permissions", {})
    found = []
    if perms.get("allow") != allow:
        found.append("skills/reducing-agent-prompts.md: the allow list differs from what exakit skills-install writes")
    if perms.get("deny") != deny:
        found.append("skills/reducing-agent-prompts.md: the deny list differs from what exakit skills-install writes")
    if f"{len(allow)} allow entries and {len(deny)} deny entries" not in text:
        found.append(f"skills/reducing-agent-prompts.md does not say '{len(allow)} allow entries and {len(deny)} deny entries'")
    return found


def mention_findings() -> list[str]:
    """Every `exakit <word>` an agent can read names a real command or page."""
    valid = valid_words()
    found: list[str] = []
    files = [REPO / name for name in PROSE] + [p for g in PROSE_GLOBS for p in REPO.glob(g)]
    for path in sorted({p for p in files if p.is_file()}):
        found += [f"{path.relative_to(REPO)}:{n}: exakit {w} is not a command" for n, w in _markdown_words(path) if w not in valid]
    for path in sorted((REPO / "help").glob("*.json")):
        for _n, word in _json_words(path):
            if word not in valid and word not in NOT_COMMANDS:
                found.append(f"{path.relative_to(REPO)}: exakit {word} is not a command")
    for path in sorted((REPO / "exakit").rglob("*.py")):
        for n, word in _code_words(path):
            if word not in valid and word not in NOT_COMMANDS:
                found.append(f"{path.relative_to(REPO)}:{n}: exakit {word} is not a command")
    return found


def _markdown_words(path: Path):
    fenced = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        words = [m.group(1) for m in _MD_CODE.finditer(line)]
        if fenced:
            match = _CODE_LINE.match(line)
            words += [match.group(1)] if match else []
        yield from ((n, w) for w in words)


def _json_words(path: Path):
    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
    for text in strings(json.loads(path.read_text(encoding="utf-8"))):
        yield from ((0, m.group(1)) for m in _IN_STRING.finditer(text))


def _code_words(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield from ((node.lineno, m.group(1)) for m in _IN_STRING.finditer(node.value))


def findings() -> list[str]:
    """Everything that disagrees."""
    return surface_findings() + mention_findings()


if __name__ == "__main__":
    problems = findings()
    print("\n".join(problems) or "every surface agrees")
    sys.exit(1 if problems else 0)
