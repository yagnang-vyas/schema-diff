"""Normalization of types, defaults and expressions.

Two schemas that are logically the same must normalize to identical values even when
the catalogs report them differently. The rules are deliberately textual and
conservative: they remove only spelling differences that cannot change meaning.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from schemadiff.urls import MYSQL, POSTGRESQL

# A quoted segment: 'string', "identifier" or `identifier`. Everything outside these
# segments may be re-cased and re-spaced; quoted content is never touched.
_QUOTED = re.compile(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`(?:[^`]|``)*`)")
_WS = re.compile(r"\s+")
_CHARSET_INTRODUCER = re.compile(r"_(?:utf8mb4|utf8mb3|utf8|latin1|ascii|binary)\s*$")

_PG_TZ = re.compile(r"^(timestamp|time)(\(\d+\))? (with|without) time zone$")
_ARRAY_SUFFIX = re.compile(r"((?:\[\d*\])+)$")
_PG_ALIASES = {
    "character varying": "varchar",
    "character": "char",
    "bpchar": "char",
    "int": "integer",
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "serial": "integer",
    "bigserial": "bigint",
    "smallserial": "smallint",
    "bool": "boolean",
    "float4": "real",
    "float8": "double precision",
    "decimal": "numeric",
    "bit varying": "varbit",
}

_MYSQL_INT = re.compile(r"^(tinyint|smallint|mediumint|integer|int|bigint)(?:\((\d+)\))?(.*)$")
_MYSQL_ALIASES = {
    "bool": "tinyint(1)",
    "boolean": "tinyint(1)",
    "numeric": "decimal",
    "dec": "decimal",
    "fixed": "decimal",
    "real": "double",
}
_MYSQL_BASE = re.compile(r"^([a-z ]+?)(\(.*\))?(\s+.*)?$")

_PG_CAST = re.compile(
    r"::\s*(?:"
    r"character varying|double precision|bit varying|"
    r"timestamp(?:\(\d+\))? (?:with|without) time zone|"
    r"time(?:\(\d+\))? (?:with|without) time zone|"
    r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?"
    r")(?:\(\s*\d+(?:\s*,\s*\d+)?\s*\))?(?:\[\d*\])*",
    re.IGNORECASE,
)
_NOW = re.compile(r"^(?:now|current_timestamp|transaction_timestamp)(?:\(\s*(\d*)\s*\))?$")


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _map_unquoted(text: str, fn: Callable[[str], str]) -> str:
    """Apply a function to the unquoted segments only."""
    parts = _QUOTED.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = fn(parts[i])
    return "".join(parts)


def _outer_parens_wrap_all(text: str) -> bool:
    """True when the "(" at index 0 is closed by the ")" at the last index."""
    depth = 0
    parts = _QUOTED.split(text)
    pos = 0
    for i, part in enumerate(parts):
        if i % 2 == 0:
            for ch in part:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0 and pos + 1 < len(text):
                        return False
                pos += 1
        else:
            pos += len(part)
    return depth == 0


def _strip_outer_parens(text: str) -> str:
    while text.startswith("(") and text.endswith(")") and _outer_parens_wrap_all(text):
        text = text[1:-1].strip()
    return text


def normalize_expression(dialect: str, raw: str) -> str:
    """Collapse whitespace, lower-case keywords and drop redundant outer parentheses.

    Quoted strings and identifiers keep their exact content. Semantically equivalent
    but differently written expressions may still compare unequal.
    """
    parts = _QUOTED.split(raw)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            part = part.lower()
            if dialect == MYSQL and i + 1 < len(parts) and parts[i + 1].startswith("'"):
                part = _CHARSET_INTRODUCER.sub("", part)
            part = _WS.sub(" ", part)
            part = re.sub(r"\(\s+", "(", part)
            part = re.sub(r"\s+\)", ")", part)
            part = re.sub(r"\s*,\s*", ", ", part)
            parts[i] = part
        elif part.startswith("`"):
            parts[i] = part[1:-1].replace("``", "`").lower()
    return _strip_outer_parens("".join(parts).strip())


def normalize_type(dialect: str, raw: str) -> str:
    """Canonical lower-case type name with parameters."""
    if dialect == POSTGRESQL:
        return _normalize_pg_type(raw)
    return _normalize_mysql_type(raw)


def _normalize_pg_type(raw: str) -> str:
    text = collapse_ws(raw)
    if '"' in text:  # quoted (case-sensitive) user type: keep exactly
        return text
    text = text.lower()
    array = ""
    if m := _ARRAY_SUFFIX.search(text):
        array = m.group(1)
        text = text[: m.start()].strip()
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*,\s*", ",", text)
    text = re.sub(r"\s*\)", ")", text)
    if m := _PG_TZ.match(text):
        kind, precision, zone = m.groups()
        text = kind + ("tz" if zone == "with" else "") + (precision or "")
    else:
        base_match = re.match(r"^([a-z0-9_ .]+?)(\(.*\))?$", text)
        if base_match:
            base = _PG_ALIASES.get(base_match.group(1), base_match.group(1))
            text = base + (base_match.group(2) or "")
    return text + array


def _normalize_mysql_type(raw: str) -> str:
    text = collapse_ws(raw)
    head = re.match(r"^(enum|set)\s*\(", text, re.IGNORECASE)
    if head:  # keep the member literals exactly; only the keyword is case-folded
        return head.group(1).lower() + text[head.end() - 1 :]
    text = text.lower().replace("double precision", "double")
    text = re.sub(r"\s*,\s*", ",", text)
    if m := _MYSQL_INT.match(text):
        base, width, rest = m.group(1), m.group(2), m.group(3)
        if base == "integer":
            base = "int"
        keep_width = base == "tinyint" and width == "1"
        return base + (f"({width})" if keep_width else "") + rest
    if m := _MYSQL_BASE.match(text):
        base = _MYSQL_ALIASES.get(m.group(1), m.group(1))
        return base + (m.group(2) or "") + (m.group(3) or "")
    return text


def is_sequence_default(raw: str) -> bool:
    """True for PostgreSQL serial-style defaults: nextval('seq'::regclass)."""
    return raw.lstrip().lower().startswith("nextval(")


def normalize_default(dialect: str, raw: str | None) -> str | None:
    """Normalize a column default; NULL defaults and "no default" are the same thing."""
    if raw is None:
        return None
    text = raw.strip()
    if dialect == POSTGRESQL:
        text = _map_unquoted(text, lambda seg: _PG_CAST.sub("", seg))
    text = normalize_expression(dialect, text)
    if m := _NOW.match(text):
        text = "current_timestamp" + (f"({m.group(1)})" if m.group(1) else "")
    if text in ("", "null"):
        return None
    return text


def hash_definition(dialect: str, raw: str) -> str:
    """Stable hash of a normalized view definition."""
    text = normalize_expression(dialect, raw.strip().rstrip(";"))
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()
