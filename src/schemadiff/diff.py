"""Pure schema comparison: (Schema, Schema, Options) -> list[Change]. No I/O."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from fnmatch import fnmatchcase
from typing import Any, TypeVar

from schemadiff.errors import DialectMismatchError
from schemadiff.model import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Schema,
    Table,
    UniqueConstraint,
)

DEFAULT_EXCLUDES = (
    "alembic_version",
    "django_migrations",
    "migrations",
    "schema_migrations",
    "flyway_schema_history",
)

EXPRESSION_NOTE = (
    "expressions are compared textually after normalization; "
    "differently written but equivalent expressions may be reported"
)


class Severity(IntEnum):
    NOTE = 1
    WARNING = 2
    ERROR = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Options:
    ignore_index_names: bool = False
    ignore_constraint_names: bool = False
    ignore_column_order: bool = True
    include_tables: tuple[str, ...] = ()
    exclude_tables: tuple[str, ...] = DEFAULT_EXCLUDES


@dataclass(frozen=True)
class Change:
    kind: str  # added | removed | changed
    object: str
    path: str
    severity: Severity
    table: str | None = None
    attribute: str | None = None
    source: Any = None
    target: Any = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "object": self.object,
            "path": self.path,
            "table": self.table,
            "severity": self.severity.label,
            "attribute": self.attribute,
            "source": self.source,
            "target": self.target,
            "note": self.note,
        }


_OBJECT_ORDER = {
    "table": 0,
    "column": 1,
    "primary_key": 2,
    "index": 3,
    "unique_constraint": 4,
    "foreign_key": 5,
    "check_constraint": 6,
    "view": 7,
    "enum": 8,
}

T = TypeVar("T")


def table_selected(name: str, options: Options) -> bool:
    if options.include_tables and not any(fnmatchcase(name, g) for g in options.include_tables):
        return False
    return not any(fnmatchcase(name, g) for g in options.exclude_tables)


def diff_schemas(source: Schema, target: Schema, options: Options | None = None) -> list[Change]:
    options = options or Options()
    if source.dialect != target.dialect:
        raise DialectMismatchError(
            f"cannot compare a {source.dialect} schema with a {target.dialect} schema"
        )
    changes: list[Change] = []
    src_tables = {n: t for n, t in source.tables.items() if table_selected(n, options)}
    tgt_tables = {n: t for n, t in target.tables.items() if table_selected(n, options)}
    for name in sorted(src_tables.keys() - tgt_tables.keys()):
        changes.append(Change("removed", "table", name, Severity.ERROR, name))
    for name in sorted(tgt_tables.keys() - src_tables.keys()):
        changes.append(Change("added", "table", name, Severity.ERROR, name))
    for name in sorted(src_tables.keys() & tgt_tables.keys()):
        changes.extend(_diff_table(src_tables[name], tgt_tables[name], options))
    changes.extend(_diff_views(source.views, target.views))
    changes.extend(_diff_enums(source.enums, target.enums))
    return sorted(changes, key=_sort_key)


def _sort_key(change: Change) -> tuple[Any, ...]:
    return (
        change.table is None,
        change.table or "",
        _OBJECT_ORDER[change.object],
        change.path,
        change.kind,
        change.attribute or "",
    )


def count_by_severity(changes: list[Change]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "note": 0}
    for change in changes:
        counts[change.severity.label] += 1
    return counts


def exceeds(changes: list[Change], fail_on: str) -> bool:
    """True when any change is at or above the --fail-on threshold."""
    if fail_on == "never":
        return False
    threshold = Severity[fail_on.upper()]
    return any(c.severity >= threshold for c in changes)


# --- tables ---------------------------------------------------------------------------


def _diff_table(src: Table, tgt: Table, options: Options) -> list[Change]:
    name = src.name
    changes: list[Change] = []
    if src.comment != tgt.comment:
        changes.append(
            Change(
                "changed", "table", name, Severity.NOTE, name, "comment", src.comment, tgt.comment
            )
        )
    changes.extend(_diff_columns(name, src, tgt, options))
    changes.extend(_diff_primary_key(name, src.primary_key, tgt.primary_key))
    changes.extend(
        _diff_named(
            name,
            "index",
            src.indexes,
            tgt.indexes,
            by_signature=options.ignore_index_names,
            signature=lambda i: (i.columns, i.unique, i.predicate, i.method),
            describe=_describe_index,
            attributes=("columns", "unique", "predicate", "method"),
            severity=Severity.WARNING,
        )
    )
    changes.extend(
        _diff_named(
            name,
            "unique_constraint",
            src.unique_constraints,
            tgt.unique_constraints,
            by_signature=options.ignore_constraint_names,
            signature=lambda u: (u.columns,),
            describe=lambda u: f"({', '.join(u.columns)})",
            attributes=("columns",),
            severity=Severity.WARNING,
        )
    )
    changes.extend(
        _diff_named(
            name,
            "foreign_key",
            src.foreign_keys,
            tgt.foreign_keys,
            by_signature=options.ignore_constraint_names,
            signature=lambda f: (f.columns, f.ref_table, f.ref_columns, f.on_delete, f.on_update),
            describe=_describe_fk,
            attributes=("columns", "ref_table", "ref_columns", "on_delete", "on_update"),
            severity=Severity.ERROR,
        )
    )
    changes.extend(
        _diff_named(
            name,
            "check_constraint",
            src.check_constraints,
            tgt.check_constraints,
            by_signature=options.ignore_constraint_names,
            signature=lambda c: (c.expression,),
            describe=lambda c: c.expression,
            attributes=("expression",),
            severity=Severity.WARNING,
            note=EXPRESSION_NOTE,
        )
    )
    return changes


def _diff_columns(table: str, src: Table, tgt: Table, options: Options) -> list[Change]:
    changes: list[Change] = []
    for col in sorted(src.columns.keys() - tgt.columns.keys()):
        changes.append(
            Change(
                "removed",
                "column",
                f"{table}.{col}",
                Severity.ERROR,
                table,
                source=_describe_column(src.columns[col]),
            )
        )
    for col in sorted(tgt.columns.keys() - src.columns.keys()):
        changes.append(
            Change(
                "added",
                "column",
                f"{table}.{col}",
                Severity.ERROR,
                table,
                target=_describe_column(tgt.columns[col]),
            )
        )
    for col in sorted(src.columns.keys() & tgt.columns.keys()):
        changes.extend(_diff_column(table, src.columns[col], tgt.columns[col]))
    if not options.ignore_column_order:
        common = src.columns.keys() & tgt.columns.keys()
        src_order = [
            c for c in sorted(src.columns, key=lambda n: src.columns[n].position) if c in common
        ]
        tgt_order = [
            c for c in sorted(tgt.columns, key=lambda n: tgt.columns[n].position) if c in common
        ]
        if src_order != tgt_order:
            changes.append(
                Change(
                    "changed",
                    "table",
                    table,
                    Severity.NOTE,
                    table,
                    "column_order",
                    src_order,
                    tgt_order,
                )
            )
    return changes


def _diff_column(table: str, src: Column, tgt: Column) -> list[Change]:
    path = f"{table}.{src.name}"
    changes: list[Change] = []

    def add(attribute: str, severity: Severity, a: Any, b: Any, note: str | None = None) -> None:
        if a != b:
            changes.append(
                Change("changed", "column", path, severity, table, attribute, a, b, note)
            )

    add("type", Severity.ERROR, src.type, tgt.type)
    add("nullable", Severity.ERROR, src.nullable, tgt.nullable)
    add("default", Severity.WARNING, src.default, tgt.default)
    add("identity", Severity.WARNING, src.identity, tgt.identity)
    if (src.generated is None) != (tgt.generated is None):
        add("generated", Severity.WARNING, src.generated, tgt.generated)
    else:
        add("generated", Severity.NOTE, src.generated, tgt.generated, EXPRESSION_NOTE)
    add("collation", Severity.NOTE, src.collation, tgt.collation)
    add("charset", Severity.NOTE, src.charset, tgt.charset)
    add("comment", Severity.NOTE, src.comment, tgt.comment)
    return changes


def _diff_primary_key(table: str, src: tuple[str, ...], tgt: tuple[str, ...]) -> list[Change]:
    path = f"{table}.primary_key"
    if src == tgt:
        return []
    if src and not tgt:
        return [Change("removed", "primary_key", path, Severity.ERROR, table, source=list(src))]
    if tgt and not src:
        return [Change("added", "primary_key", path, Severity.ERROR, table, target=list(tgt))]
    return [
        Change(
            "changed", "primary_key", path, Severity.ERROR, table, "columns", list(src), list(tgt)
        )
    ]


def _diff_named(
    table: str,
    obj: str,
    src: dict[str, T],
    tgt: dict[str, T],
    *,
    by_signature: bool,
    signature: Callable[[T], tuple[Any, ...]],
    describe: Callable[[T], str],
    attributes: tuple[str, ...],
    severity: Severity,
    note: str | None = None,
) -> list[Change]:
    """Diff a name-keyed collection, matching by name or (ignoring names) by signature."""
    removed: list[str] = []
    added: list[str] = []
    common: list[str] = []
    if by_signature:
        unmatched_tgt: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for name in sorted(tgt):
            unmatched_tgt[signature(tgt[name])].append(name)
        for name in sorted(src):
            candidates = unmatched_tgt.get(signature(src[name]))
            if candidates:
                candidates.pop(0)
            else:
                removed.append(name)
        added = sorted(n for names in unmatched_tgt.values() for n in names)
    else:
        removed = sorted(src.keys() - tgt.keys())
        added = sorted(tgt.keys() - src.keys())
        common = sorted(src.keys() & tgt.keys())

    changes: list[Change] = []
    for name in removed:
        changes.append(
            Change("removed", obj, f"{table}.{name}", severity, table, source=describe(src[name]))
        )
    for name in added:
        changes.append(
            Change("added", obj, f"{table}.{name}", severity, table, target=describe(tgt[name]))
        )
    for name in common:
        for attribute in attributes:
            a = _attr(src[name], attribute)
            b = _attr(tgt[name], attribute)
            if a != b:
                changes.append(
                    Change(
                        "changed", obj, f"{table}.{name}", severity, table, attribute, a, b, note
                    )
                )
    return changes


def _attr(obj: Any, attribute: str) -> Any:
    value = getattr(obj, attribute)
    return list(value) if isinstance(value, tuple) else value


# --- views and enums --------------------------------------------------------------------


def _diff_views(src: dict[str, str], tgt: dict[str, str]) -> list[Change]:
    changes: list[Change] = []
    for name in sorted(src.keys() - tgt.keys()):
        changes.append(Change("removed", "view", name, Severity.WARNING, source=src[name]))
    for name in sorted(tgt.keys() - src.keys()):
        changes.append(Change("added", "view", name, Severity.WARNING, target=tgt[name]))
    for name in sorted(src.keys() & tgt.keys()):
        if src[name] != tgt[name]:
            changes.append(
                Change(
                    "changed",
                    "view",
                    name,
                    Severity.WARNING,
                    attribute="definition",
                    source=src[name],
                    target=tgt[name],
                )
            )
    return changes


def _diff_enums(src: dict[str, tuple[str, ...]], tgt: dict[str, tuple[str, ...]]) -> list[Change]:
    changes: list[Change] = []
    for name in sorted(src.keys() - tgt.keys()):
        changes.append(Change("removed", "enum", name, Severity.WARNING, source=list(src[name])))
    for name in sorted(tgt.keys() - src.keys()):
        changes.append(Change("added", "enum", name, Severity.WARNING, target=list(tgt[name])))
    for name in sorted(src.keys() & tgt.keys()):
        if src[name] != tgt[name]:
            changes.append(
                Change(
                    "changed",
                    "enum",
                    name,
                    Severity.WARNING,
                    attribute="labels",
                    source=list(src[name]),
                    target=list(tgt[name]),
                )
            )
    return changes


# --- descriptions for added / removed objects --------------------------------------------


def _describe_column(col: Column) -> str:
    parts = [col.type, "null" if col.nullable else "not null"]
    if col.default is not None:
        parts.append(f"default {col.default}")
    if col.identity:
        parts.append("identity")
    if col.generated is not None:
        parts.append(f"generated as {col.generated}")
    return " ".join(parts)


def _describe_index(index: Index) -> str:
    text = f"({', '.join(index.columns)})"
    if index.unique:
        text = "unique " + text
    if index.method:
        text += f" using {index.method}"
    if index.predicate:
        text += f" where {index.predicate}"
    return text


def _describe_fk(fk: ForeignKey) -> str:
    return (
        f"({', '.join(fk.columns)}) -> {fk.ref_table}({', '.join(fk.ref_columns)}) "
        f"on delete {fk.on_delete.lower()} on update {fk.on_update.lower()}"
    )


__all__ = [
    "DEFAULT_EXCLUDES",
    "Change",
    "CheckConstraint",
    "Options",
    "Severity",
    "UniqueConstraint",
    "count_by_severity",
    "diff_schemas",
    "exceeds",
    "table_selected",
]
