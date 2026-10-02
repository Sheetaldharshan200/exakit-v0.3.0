"""Schema and table names the loader may use unquoted: letters first, letters, digits and underscores after, no reserved word, at most 128 characters."""

from __future__ import annotations

import hashlib
import re
import unicodedata

MAX_IDENTIFIER = 128            # Exasol's limit for a schema or table name
KEYWORDS_SQL = ("SELECT 'EXAKIT_KW[' || LISTAGG(\"KEYWORD\", ',') WITHIN GROUP (ORDER BY \"KEYWORD\") || ']' AS K "
                "FROM SYS.EXA_SQL_KEYWORDS WHERE \"RESERVED\"")

# Always treated as reserved, whatever the database answers: a word here that the database does not reserve only costs a
# "_DATA" suffix, while a reserved word missing from it would break CREATE SCHEMA - and a load whose keyword query fails
# must name things exactly as one whose query worked.
BUILT_IN_RESERVED = frozenset((
    "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "AT", "BETWEEN", "BY", "CASE", "CAST", "CHECK", "COLUMN", "CONNECT",
    "CONSTRAINT", "CREATE", "CROSS", "CURRENT", "DATE", "DAY", "DEFAULT", "DELETE", "DESC", "DISTINCT", "DROP", "ELSE",
    "END", "ESCAPE", "EXCEPT", "EXISTS", "FALSE", "FETCH", "FOR", "FOREIGN", "FROM", "FULL", "FUNCTION", "GRANT", "GROUP",
    "HAVING", "HOUR", "IF", "IN", "INNER", "INSERT", "INTERSECT", "INTERVAL", "INTO", "IS", "JOIN", "LEFT", "LEVEL", "LIKE",
    "LIMIT", "LOCAL", "MINUS", "MINUTE", "MONTH", "NATURAL", "NOT", "NULL", "OF", "ON", "OR", "ORDER", "OUTER", "PRIMARY",
    "PRIOR", "REFERENCES", "REVOKE", "RIGHT", "ROLE", "ROW", "ROWS", "SCHEMA", "SECOND", "SELECT", "SESSION", "SET", "SOME",
    "START", "TABLE", "THEN", "TIME", "TIMESTAMP", "TO", "TRUE", "UNION", "UNIQUE", "UNKNOWN", "UPDATE", "USER", "USING",
    "VALUE", "VALUES", "VIEW", "WHEN", "WHERE", "WITH", "YEAR",
))

_VALID = re.compile(r"[A-Z][A-Z0-9_]*")


def parse_keywords(out: str) -> frozenset[str]:
    """The reserved words in the keyword query's answer; empty when it did not answer."""
    match = re.search(r"EXAKIT_KW\[([^\]]*)\]", out or "")
    return frozenset(w.strip().upper() for w in match.group(1).split(",") if w.strip()) if match else frozenset()


def identifier(text: str, *, lead: str, reserved: frozenset[str] = BUILT_IN_RESERVED, key: str = "") -> str:
    """``text`` as a name usable unquoted. Accents are dropped (données -> DONNEES), anything else becomes one underscore;
    a name starting with a digit gets ``lead`` in front (2024 -> DATA_2024), a reserved word gets ``_DATA`` after (ORDER -> ORDER_DATA),
    and a name over 128 characters is cut and ends in a short digest of ``key`` (or the text) so two long names stay apart."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"_+", "_", re.sub(r"[^A-Z0-9_]+", "_", ascii_text.upper())).strip("_") or lead
    if not name[0].isalpha():
        name = f"{lead}_{name}"
    if name in reserved | BUILT_IN_RESERVED:
        name = f"{name}_DATA"
    return fit(name, key or text)


def fit(name: str, key: str) -> str:
    """``name`` cut to the identifier limit, with a digest of ``key`` at the end when it had to be cut."""
    if len(name) <= MAX_IDENTIFIER:
        return name
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8].upper()
    return f"{name[: MAX_IDENTIFIER - 9].rstrip('_')}_{digest}"


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
