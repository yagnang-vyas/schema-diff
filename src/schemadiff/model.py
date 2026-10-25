"""Normalized, engine-neutral schema model (all values already normalized)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Column:
    name: str
    position: int  # 1-based rank among the table's columns, gaps removed
    type: str
    nullable: bool
    default: str | None = None
    identity: bool = False
    generated: str | None = None
    collation: str | None = None
    charset: str | None = None
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "type": self.type,
            "nullable": self.nullable,
            "default": self.default,
            "identity": self.identity,
            "generated": self.generated,
            "collation": self.collation,
            "charset": self.charset,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Column:
        return cls(
            name=name,
            position=int(data["position"]),
            type=data["type"],
            nullable=bool(data["nullable"]),
            default=data.get("default"),
            identity=bool(data.get("identity", False)),
            generated=data.get("generated"),
            collation=data.get("collation"),
            charset=data.get("charset"),
            comment=data.get("comment"),
        )


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]  # column names or normalized expressions, in key order
    unique: bool = False
    predicate: str | None = None
    method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "unique": self.unique,
            "predicate": self.predicate,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Index:
        return cls(
            name=name,
            columns=tuple(data["columns"]),
            unique=bool(data.get("unique", False)),
            predicate=data.get("predicate"),
            method=data.get("method"),
        )


@dataclass(frozen=True)
class UniqueConstraint:
    name: str
    columns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"columns": list(self.columns)}

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> UniqueConstraint:
        return cls(name=name, columns=tuple(data["columns"]))


@dataclass(frozen=True)
class ForeignKey:
    name: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    on_delete: str = "NO ACTION"
    on_update: str = "NO ACTION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "ref_table": self.ref_table,
            "ref_columns": list(self.ref_columns),
            "on_delete": self.on_delete,
            "on_update": self.on_update,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ForeignKey:
        return cls(
            name=name,
            columns=tuple(data["columns"]),
            ref_table=data["ref_table"],
            ref_columns=tuple(data["ref_columns"]),
            on_delete=data.get("on_delete", "NO ACTION"),
            on_update=data.get("on_update", "NO ACTION"),
        )


@dataclass(frozen=True)
class CheckConstraint:
    name: str
    expression: str

    def to_dict(self) -> dict[str, Any]:
        return {"expression": self.expression}

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> CheckConstraint:
        return cls(name=name, expression=data["expression"])


@dataclass(frozen=True)
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    primary_key: tuple[str, ...] = ()
    indexes: dict[str, Index] = field(default_factory=dict)
    unique_constraints: dict[str, UniqueConstraint] = field(default_factory=dict)
    foreign_keys: dict[str, ForeignKey] = field(default_factory=dict)
    check_constraints: dict[str, CheckConstraint] = field(default_factory=dict)
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": {k: v.to_dict() for k, v in sorted(self.columns.items())},
            "primary_key": list(self.primary_key),
            "indexes": {k: v.to_dict() for k, v in sorted(self.indexes.items())},
            "unique_constraints": {
                k: v.to_dict() for k, v in sorted(self.unique_constraints.items())
            },
            "foreign_keys": {k: v.to_dict() for k, v in sorted(self.foreign_keys.items())},
            "check_constraints": {
                k: v.to_dict() for k, v in sorted(self.check_constraints.items())
            },
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Table:
        return cls(
            name=name,
            columns={k: Column.from_dict(k, v) for k, v in data["columns"].items()},
            primary_key=tuple(data.get("primary_key", [])),
            indexes={k: Index.from_dict(k, v) for k, v in data.get("indexes", {}).items()},
            unique_constraints={
                k: UniqueConstraint.from_dict(k, v)
                for k, v in data.get("unique_constraints", {}).items()
            },
            foreign_keys={
                k: ForeignKey.from_dict(k, v) for k, v in data.get("foreign_keys", {}).items()
            },
            check_constraints={
                k: CheckConstraint.from_dict(k, v)
                for k, v in data.get("check_constraints", {}).items()
            },
            comment=data.get("comment"),
        )


@dataclass(frozen=True)
class Schema:
    dialect: str
    schema: str
    server_version: str = ""
    tables: dict[str, Table] = field(default_factory=dict)
    views: dict[str, str] = field(default_factory=dict)  # name -> hash of normalized definition
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)  # name -> labels in order
