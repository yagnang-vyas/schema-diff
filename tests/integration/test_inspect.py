"""Inspection of the drift fixture schemas on real databases."""

from __future__ import annotations

from schemadiff.inspect import inspect_database
from schemadiff.model import Schema
from schemadiff.urls import parse_url
from tests.integration.conftest import Db


def read(db: Db, schema: str) -> Schema:
    url, dialect = parse_url(db.url)
    return inspect_database(url, dialect, schema)


def test_inspected_details(drift: Db) -> None:
    schema = read(drift, "drift_source")
    assert schema.dialect == drift.dialect
    assert schema.server_version[0].isdigit()
    users = schema.tables["users"]
    assert users.primary_key == ("id",)
    assert users.columns["id"].identity
    assert users.columns["id"].default is None
    assert users.columns["status"].default == "'active'"
    assert users.columns["email"].comment == "login email"
    assert users.columns["full_label"].generated is not None
    assert [c.position for c in users.columns.values()] == list(range(1, len(users.columns) + 1))
    assert schema.tables["orders"].foreign_keys["orders_user_fkey"].on_delete == "CASCADE"
    assert set(schema.views) == {"active_users", "order_totals"}
    assert "audit_log" in schema.tables
    if drift.dialect == "postgresql":
        assert schema.enums == {"status_enum": ("active", "inactive", "pending")}
        assert users.unique_constraints["users_email_key"].columns == ("email",)
        assert schema.tables["orders"].indexes["idx_orders_open"].predicate is not None
    else:
        assert users.indexes["users_email_key"].unique
