from __future__ import annotations

import pytest

from schemadiff.normalize import (
    hash_definition,
    is_sequence_default,
    normalize_default,
    normalize_expression,
    normalize_type,
)

PG = "postgresql"
MY = "mysql"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("character varying(255)", "varchar(255)"),
        ("character varying", "varchar"),
        ("character(3)", "char(3)"),
        ("int4", "integer"),
        ("int8", "bigint"),
        ("int2", "smallint"),
        ("bool", "boolean"),
        ("float8", "double precision"),
        ("float4", "real"),
        ("decimal(10, 2)", "numeric(10,2)"),
        ("NUMERIC(10,2)", "numeric(10,2)"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp(3) without time zone", "timestamp(3)"),
        ("timestamp with time zone", "timestamptz"),
        ("timestamp(6) with time zone", "timestamptz(6)"),
        ("time without time zone", "time"),
        ("time with time zone", "timetz"),
        ("character varying(10)[]", "varchar(10)[]"),
        ("integer[]", "integer[]"),
        ("bit varying(8)", "varbit(8)"),
        ("status_enum", "status_enum"),
        ("  TEXT ", "text"),
        ('"MixedCase"', '"MixedCase"'),
    ],
)
def test_postgres_types(raw: str, expected: str) -> None:
    assert normalize_type(PG, raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("int(11)", "int"),
        ("int", "int"),
        ("integer", "int"),
        ("int(10) unsigned", "int unsigned"),
        ("bigint(20)", "bigint"),
        ("tinyint(1)", "tinyint(1)"),
        ("tinyint(4)", "tinyint"),
        ("tinyint", "tinyint"),
        ("bool", "tinyint(1)"),
        ("boolean", "tinyint(1)"),
        ("numeric(10, 2)", "decimal(10,2)"),
        ("DECIMAL(10,2) UNSIGNED", "decimal(10,2) unsigned"),
        ("double precision", "double"),
        ("VARCHAR(255)", "varchar(255)"),
        ("datetime(6)", "datetime(6)"),
        ("ENUM('Open','closed')", "enum('Open','closed')"),
        ("set('A','b')", "set('A','b')"),
        ("text", "text"),
    ],
)
def test_mysql_types(raw: str, expected: str) -> None:
    assert normalize_type(MY, raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("'active'::character varying", "'active'"),
        ("'active'::text", "'active'"),
        ("(0)::numeric", "0"),
        ("0", "0"),
        ("'a::b'::text", "'a::b'"),
        ("NULL::character varying", None),
        ("NULL", None),
        ("now()", "current_timestamp"),
        ("CURRENT_TIMESTAMP", "current_timestamp"),
        ("transaction_timestamp()", "current_timestamp"),
        ("'{}'::integer[]", "'{}'"),
        ("'2020-01-01'::timestamp without time zone", "'2020-01-01'"),
        ("'x'::public.mood", "'x'"),
        ("TRUE", "true"),
        ("'Mixed Case'", "'Mixed Case'"),
        ("  ", None),
        (None, None),
    ],
)
def test_postgres_defaults(raw: str | None, expected: str | None) -> None:
    assert normalize_default(PG, raw) == expected


def test_default_spellings_agree() -> None:
    assert normalize_default(PG, "now()") == normalize_default(PG, "CURRENT_TIMESTAMP")
    assert normalize_default(PG, "now()") != normalize_default(PG, "CURRENT_TIMESTAMP(3)")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CURRENT_TIMESTAMP", "current_timestamp"),
        ("CURRENT_TIMESTAMP(6)", "current_timestamp(6)"),
        ("now()", "current_timestamp"),
        ("(uuid())", "uuid()"),
        ("_utf8mb4'x'", "'x'"),
        ("`col` + 1", "col + 1"),
        ("NULL", None),
    ],
)
def test_mysql_defaults(raw: str, expected: str | None) -> None:
    assert normalize_default(MY, raw) == expected


def test_sequence_defaults() -> None:
    assert is_sequence_default("nextval('users_id_seq'::regclass)")
    assert is_sequence_default("  NEXTVAL('x')")
    assert not is_sequence_default("0")


def test_expressions_collapse_whitespace_and_case() -> None:
    assert normalize_expression(PG, "((PRICE   >  0)\n AND (qty < 10))") == (
        "(price > 0) and (qty < 10)"
    )


def test_expressions_strip_only_wrapping_parentheses() -> None:
    assert normalize_expression(PG, "((a > 0))") == "a > 0"
    assert normalize_expression(PG, "(a > 0) and (b > 0)") == "(a > 0) and (b > 0)"
    assert normalize_expression(PG, "( a )") == "a"


def test_expressions_keep_quoted_content() -> None:
    assert normalize_expression(PG, "(status = 'A  b')") == "status = 'A  b'"
    assert normalize_expression(PG, 'lower("MixedCase")') == 'lower("MixedCase")'
    assert normalize_expression(PG, "(x = ')(')") == "x = ')('"


def test_mysql_expressions_drop_backticks_and_charset_introducers() -> None:
    assert normalize_expression(MY, "(`price` > 0)") == "price > 0"
    assert normalize_expression(MY, "(`name` <> _utf8mb4'A')") == "name <> 'A'"
    assert normalize_expression(MY, "`a`,`b`") == "a, b"


def test_view_hash_ignores_layout_not_content() -> None:
    a = hash_definition(PG, "SELECT id,\n   email\n FROM users WHERE x = 'A';")
    b = hash_definition(PG, "select id, email from users where x = 'A'")
    c = hash_definition(PG, "select id, email from users where x = 'a'")
    assert a == b
    assert a != c
    assert a.startswith("sha256:")
