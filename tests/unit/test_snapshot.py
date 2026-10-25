from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemadiff import snapshot
from schemadiff.errors import SnapshotError
from schemadiff.model import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Schema,
    Table,
    UniqueConstraint,
)


def sample_schema() -> Schema:
    users = Table(
        name="users",
        columns={
            "id": Column("id", 1, "integer", False, identity=True),
            "email": Column("email", 2, "varchar(255)", False, comment="login"),
            "full": Column("full", 3, "text", True, generated="a || b", collation="C"),
        },
        primary_key=("id",),
        indexes={"idx_email": Index("idx_email", ("email",), True, "email is not null", "btree")},
        unique_constraints={"u_email": UniqueConstraint("u_email", ("email",))},
        check_constraints={"c": CheckConstraint("c", "id > 0")},
        comment="people",
    )
    orders = Table(
        name="orders",
        columns={"id": Column("id", 1, "bigint", False), "uid": Column("uid", 2, "integer", False)},
        primary_key=("id",),
        foreign_keys={
            "fk": ForeignKey("fk", ("uid",), "users", ("id",), "CASCADE", "NO ACTION"),
        },
    )
    return Schema(
        dialect="postgresql",
        schema="public",
        server_version="16.4",
        tables={"users": users, "orders": orders},
        views={"v": "sha256:abc"},
        enums={"status": ("a", "b")},
    )


def test_round_trip(tmp_path: Path) -> None:
    schema = sample_schema()
    path = tmp_path / "s.json"
    snapshot.save(schema, path, "2026-01-01T00:00:00Z")
    assert snapshot.load(path) == schema


def test_output_is_deterministic_and_sorted() -> None:
    a = snapshot.dumps(sample_schema(), "2026-01-01T00:00:00Z")
    b = snapshot.dumps(sample_schema(), "2026-01-01T00:00:00Z")
    assert a == b
    data = json.loads(a)
    assert list(data["tables"]) == ["orders", "users"]
    assert data["schema_version"] == 1
    assert data["dialect"] == "postgresql"
    assert data["captured_at"] == "2026-01-01T00:00:00Z"
    assert a.endswith("\n")


def test_snapshot_has_no_credentials_or_hosts() -> None:
    text = snapshot.dumps(sample_schema(), "2026-01-01T00:00:00Z")
    for forbidden in ("password", "host", "://", "@"):
        assert forbidden not in text


def test_rejects_unknown_version() -> None:
    data = snapshot.to_dict(sample_schema(), "t")
    data["schema_version"] = 2
    with pytest.raises(SnapshotError, match="schema_version"):
        snapshot.loads(json.dumps(data))


def test_rejects_invalid_json_and_shapes() -> None:
    with pytest.raises(SnapshotError, match="valid JSON"):
        snapshot.loads("{nope")
    with pytest.raises(SnapshotError, match="JSON object"):
        snapshot.loads("[]")


def test_rejects_unknown_dialect_and_missing_fields() -> None:
    data = snapshot.to_dict(sample_schema(), "t")
    data["dialect"] = "oracle"
    with pytest.raises(SnapshotError, match="dialect"):
        snapshot.loads(json.dumps(data))
    data = snapshot.to_dict(sample_schema(), "t")
    del data["tables"]
    with pytest.raises(SnapshotError, match="malformed"):
        snapshot.loads(json.dumps(data))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="cannot read"):
        snapshot.load(tmp_path / "missing.json")


def test_unwritable_path(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="cannot write"):
        snapshot.save(sample_schema(), tmp_path / "no" / "dir" / "s.json")


def test_source_date_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert snapshot.captured_at_now() == "1970-01-01T00:00:00Z"
    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    assert snapshot.captured_at_now().endswith("Z")
