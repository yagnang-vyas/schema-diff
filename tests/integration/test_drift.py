"""Exact drift detection and the zero-false-positive guarantee, on real databases."""

from __future__ import annotations

from pathlib import Path

from schemadiff import snapshot
from schemadiff.diff import Options, diff_schemas
from schemadiff.inspect import inspect_database
from schemadiff.urls import parse_url
from tests.integration.conftest import Db, summarize
from tests.integration.expected import MYSQL_EXPECTED, PG_EXPECTED

EXPECTED = {"postgresql": PG_EXPECTED, "mysql": MYSQL_EXPECTED}


def read(db: Db, schema: str):  # type: ignore[no-untyped-def]
    url, dialect = parse_url(db.url)
    return inspect_database(url, dialect, schema)


def test_exact_change_list(drift: Db) -> None:
    changes = diff_schemas(read(drift, "drift_source"), read(drift, "drift_target"))
    assert summarize(changes) == EXPECTED[drift.dialect]


def test_fixture_has_at_least_fifteen_distinct_kinds_of_drift(drift: Db) -> None:
    changes = diff_schemas(read(drift, "drift_source"), read(drift, "drift_target"))
    kinds = {(c.kind, c.object, c.attribute) for c in changes}
    assert len(kinds) >= 15


def test_identical_schemas_have_zero_changes(drift: Db) -> None:
    source = read(drift, "drift_source")
    copy = read(drift, "drift_copy")
    assert diff_schemas(source, copy, Options(ignore_column_order=False)) == []
    assert diff_schemas(source, source, Options(ignore_column_order=False)) == []


def test_equivalent_spellings_are_not_reported(drift: Db) -> None:
    """equivalent_forms and order_totals are written differently but mean the same."""
    changes = diff_schemas(read(drift, "drift_source"), read(drift, "drift_target"))
    assert not [c for c in changes if c.path.startswith("equivalent_forms")]
    assert not [c for c in changes if c.path == "order_totals"]
    source = read(drift, "drift_source").tables["equivalent_forms"]
    target = read(drift, "drift_target").tables["equivalent_forms"]
    assert source.columns == target.columns
    assert source.check_constraints == target.check_constraints


def test_snapshot_comparison_equals_live_comparison(drift: Db, tmp_path: Path) -> None:
    live_source = read(drift, "drift_source")
    live_target = read(drift, "drift_target")
    snapshot.save(live_source, tmp_path / "s.json", "2026-01-01T00:00:00Z")
    snapshot.save(live_target, tmp_path / "t.json", "2026-01-01T00:00:00Z")
    snap_source = snapshot.load(tmp_path / "s.json")
    snap_target = snapshot.load(tmp_path / "t.json")
    assert snap_source == live_source
    assert snap_target == live_target
    assert diff_schemas(snap_source, snap_target) == diff_schemas(live_source, live_target)


def test_snapshots_are_deterministic_and_credential_free(drift: Db, tmp_path: Path) -> None:
    schema = read(drift, "drift_source")
    first = snapshot.dumps(schema, "2026-01-01T00:00:00Z")
    second = snapshot.dumps(read(drift, "drift_source"), "2026-01-01T00:00:00Z")
    assert first == second
    password = parse_url(drift.url)[0].password or "<none>"
    for forbidden in (password, "127.0.0.1", "localhost", "://"):
        assert forbidden not in first


def test_table_filters_on_real_schemas(drift: Db) -> None:
    source = read(drift, "drift_source")
    target = read(drift, "drift_target")
    only_tags = diff_schemas(source, target, Options(include_tables=("tags",)))
    assert [c.path for c in only_tags if c.table] == ["tags.primary_key"]
    without = diff_schemas(source, target, Options(exclude_tables=("users", "orders")))
    assert not [c for c in without if c.table in ("users", "orders")]


def test_name_insensitive_options_on_renamed_objects(scratch: Db) -> None:
    scratch.load("drift_source.sql", rename=("drift_source", "drift_renamed"))
    if scratch.dialect == "postgresql":
        scratch.run_script(
            "ALTER INDEX drift_renamed.idx_orders_open RENAME TO idx_orders_open_v2;\n"
            "ALTER TABLE drift_renamed.users RENAME CONSTRAINT users_email_key TO uq_email;\n"
            "ALTER TABLE drift_renamed.orders "
            "RENAME CONSTRAINT orders_user_fkey TO fk_orders_user;\n"
            "ALTER TABLE drift_renamed.orders RENAME CONSTRAINT orders_total_check TO ck_total;\n"
        )
    else:
        scratch.run_script(
            "ALTER TABLE drift_renamed.orders RENAME INDEX idx_orders_user_placed TO idx_up2;\n"
            "ALTER TABLE drift_renamed.users RENAME INDEX users_email_key TO uq_email;\n"
            "ALTER TABLE drift_renamed.orders DROP FOREIGN KEY orders_user_fkey;\n"
            "ALTER TABLE drift_renamed.orders ADD CONSTRAINT fk_orders_user FOREIGN KEY (user_id) "
            "REFERENCES drift_renamed.users (id) ON DELETE CASCADE;\n"
            "ALTER TABLE drift_renamed.orders DROP CHECK orders_total_check;\n"
            "ALTER TABLE drift_renamed.orders ADD CONSTRAINT ck_total CHECK (total >= 0);\n"
        )
    source = read(scratch, "drift_source")
    renamed = read(scratch, "drift_renamed")
    strict = diff_schemas(source, renamed)
    assert strict, "renames are reported when names are compared"
    assert diff_schemas(source, renamed, Options(ignore_index_names=True)) != strict
    relaxed = diff_schemas(
        source, renamed, Options(ignore_index_names=True, ignore_constraint_names=True)
    )
    assert relaxed == []


def test_strict_column_order(scratch: Db) -> None:
    if scratch.dialect == "postgresql":
        scratch.run_script(
            "CREATE SCHEMA drift_order_a;\nCREATE SCHEMA drift_order_b;\n"
            "CREATE TABLE drift_order_a.t (a int, b int, c int);\n"
            "CREATE TABLE drift_order_b.t (a int, c int, b int);\n"
        )
    else:
        scratch.run_script(
            "CREATE DATABASE drift_order_a;\nCREATE DATABASE drift_order_b;\n"
            "CREATE TABLE drift_order_a.t (a int, b int, c int);\n"
            "CREATE TABLE drift_order_b.t (a int, c int, b int);\n"
        )
    a = read(scratch, "drift_order_a")
    b = read(scratch, "drift_order_b")
    assert diff_schemas(a, b) == []
    changes = diff_schemas(a, b, Options(ignore_column_order=False))
    assert [(c.severity.label, c.attribute, c.source, c.target) for c in changes] == [
        ("note", "column_order", ["a", "b", "c"], ["a", "c", "b"])
    ]
