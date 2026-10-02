"""Schema and table names the loader may use unquoted: letters first, letters, digits and underscores after, no reserved word, at most 128 characters."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

MAX_IDENTIFIER = 128            # Exasol's limit for a schema or table name
KEYWORDS_SQL = ("SELECT 'EXAKIT_KW[' || LISTAGG(\"KEYWORD\", ',') WITHIN GROUP (ORDER BY \"KEYWORD\") || ']' AS K "
                "FROM SYS.EXA_SQL_KEYWORDS WHERE \"RESERVED\"")
WORDS_FILE = Path(__file__).resolve().parents[3] / "catalog" / "sql" / "reserved-words.json"


def _built_in() -> frozenset[str]:
    """Exasol's reserved words as the kit ships them (catalog/sql/reserved-words.json, read from the database itself).

    Every name is checked against these AND what the running database answers, so a load whose keyword query fails
    names things exactly as one whose query worked; the live answer only adds what a newer Exasol reserves.
    """
    try:
        return frozenset(str(w).upper() for w in json.loads(WORDS_FILE.read_text(encoding="utf-8"))["words"])
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()          # an incomplete kit copy: the live list still answers; tests keep the file shipped


BUILT_IN_RESERVED = _built_in()

_VALID = re.compile(r"[A-Z][A-Z0-9_]*")


def parse_keywords(out: str) -> frozenset[str]:
    """The reserved words in the keyword query's answer; empty when it did not answer."""
    match = re.search(r"EXAKIT_KW\[([^\]]*)\]", out or "")
    return frozenset(w.strip().upper() for w in match.group(1).split(",") if w.strip()) if match else frozenset()


def identifier(text: str, *, lead: str, reserved: frozenset[str] = BUILT_IN_RESERVED, key: str = "") -> str:
    """``text`` as a name usable unquoted. Accents are dropped (données -> DONNEES), anything else becomes one underscore;
    a name starting with a digit gets ``lead`` in front (2024 -> DATA_2024), a reserved word gets ``_DATA`` after
    (ORDER -> ORDER_DATA), a name with no Latin letter or digit at all is ``lead`` and a digest of the text (Отчёт ->
    T_3F2A9C1B, so two such files stay apart), and a name over 128 characters is cut and ends in a digest of ``key``."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"_+", "_", re.sub(r"[^A-Z0-9_]+", "_", ascii_text.upper())).strip("_")
    if not name:
        name = f"{lead}_{_digest(text)}" if text.strip(" ._-") else lead
    if not name[0].isalpha():
        name = f"{lead}_{name}"
    if name in reserved | BUILT_IN_RESERVED:
        name = f"{name}_DATA"
    return fit(name, key or text)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8].upper()


def fit(name: str, key: str) -> str:
    """``name`` cut to the identifier limit, with a digest of ``key`` at the end when it had to be cut."""
    if len(name) <= MAX_IDENTIFIER:
        return name
    return f"{name[: MAX_IDENTIFIER - 9].rstrip('_')}_{_digest(key)}"


def problem(name: str, reserved: frozenset[str] = BUILT_IN_RESERVED) -> str | None:
    """Why a name the user typed cannot be used unquoted, or None when it can."""
    upper = name.upper()
    if not _VALID.fullmatch(upper):
        return "a schema name starts with a letter and holds letters, digits and underscores only"
    if len(upper) > MAX_IDENTIFIER:
        return f"a schema name is at most {MAX_IDENTIFIER} characters"
    if upper in reserved | BUILT_IN_RESERVED:
        return f"{upper} is a reserved SQL word (try {upper}_DATA)"
    return None
