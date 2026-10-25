from __future__ import annotations

from dataclasses import replace

import pytest

from schemadiff.diff import (
    Change,
    Options,
    Severity,
    count_by_severity,
    diff_schemas,
    exceeds,
    table_selected,
)
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


def col(name: str, position: int = 1, type_: str = "integer", **kw: object) -> Column:
    kw.setdefault("nullable", True)
    return Column(name=name, position=position, type=type_, **kw)  # type: ignore[arg-type]


def table(name: str = "t", **kw: object) -> Table:
    columns = kw.pop("columns", None) or {"id": col("id", nullable=False)}
    return Table(name=name, columns=columns, **kw)  # type: ignore[arg-type]


def schema(*tables: Table, **kw: object) -> Schema:
    return Schema(
        dialect=str(kw.pop("dialect", "postgresql")),
        schema="s",
        tables={t.name: t for t in tables},
        **kw,  # type: ignore[arg-type]
    )


class Rows(list):  # type: ignore[type-arg]
    """Change summaries compare order-insensitively (ordering has its own test)."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, list) and sorted(self, key=str) == sorted(other, key=str)


def summary(changes: list[Change]) -> Rows:
    return Rows((c.severity.label, c.kind, c.object, c.path, c.attribute) for c in changes)


def expect(
    *rows: tuple[str, str, str, str, str | None],
) -> list[tuple[str, str, str, str, str | None]]:
    return list(rows)


def test_identical_schemas_have_no_changes() -> None:
    a = schema(table(primary_key=("id",)), views={"v": "h"}, enums={"e": ("a",)})
    assert diff_schemas(a, a) == []


def test_table_added_and_removed_are_errors() -> None:
    changes = diff_schemas(schema(table("a")), schema(table("b")))
    assert summary(changes) == expect(
        ("error", "removed", "table", "a", None),
        ("error", "added", "table", "b", None),
    )


def test_column_added_removed_and_type_nullability_errors() -> None:
    src = table(columns={"a": col("a"), "b": col("b", 2), "c": col("c", 3, "text")})
    tgt = table(
        columns={
            "a": col("a", nullable=False),
            "c": col("c", 2, "varchar(5)"),
            "d": col("d", 3),
        }
    )
    assert summary(diff_schemas(schema(src), schema(tgt))) == expect(
        ("error", "removed", "column", "t.b", None),
        ("error", "added", "column", "t.d", None),
        ("error", "changed", "column", "t.a", "nullable"),
        ("error", "changed", "column", "t.c", "type"),
    )


def test_column_attribute_severities() -> None:
    src = table(columns={"a": col("a", default="1", identity=False, comment="x", collation="C")})
    tgt = table(
        columns={"a": col("a", default="2", identity=True, comment="y", collation="D", charset="u")}
    )
    assert summary(diff_schemas(schema(src), schema(tgt))) == expect(
        ("warning", "changed", "column", "t.a", "default"),
        ("warning", "changed", "column", "t.a", "identity"),
        ("note", "changed", "column", "t.a", "collation"),
        ("note", "changed", "column", "t.a", "charset"),
        ("note", "changed", "column", "t.a", "comment"),
    )


def test_generated_column_severity() -> None:
    plain = table(columns={"a": col("a")})
    gen1 = table(columns={"a": col("a", generated="x + 1")})
    gen2 = table(columns={"a": col("a", generated="x + 2")})
    assert summary(diff_schemas(schema(plain), schema(gen1))) == [
        ("warning", "changed", "column", "t.a", "generated")
    ]
    changes = diff_schemas(schema(gen1), schema(gen2))
    assert summary(changes) == [("note", "changed", "column", "t.a", "generated")]
    assert changes[0].note is not None


def test_primary_key_changes() -> None:
    base = table(primary_key=("id",))
    assert summary(diff_schemas(schema(base), schema(table()))) == expect(
        ("error", "removed", "primary_key", "t.primary_key", None)
    )
    assert summary(diff_schemas(schema(table()), schema(base))) == [
        ("error", "added", "primary_key", "t.primary_key", None)
    ]
    wider = table(primary_key=("id", "x"))
    changes = diff_schemas(schema(base), schema(wider))
    assert summary(changes) == [("error", "changed", "primary_key", "t.primary_key", "columns")]
    assert (changes[0].source, changes[0].target) == (["id"], ["id", "x"])


def test_indexes_unique_and_checks_are_warnings() -> None:
    src = table(
        indexes={"i": Index("i", ("a",)), "j": Index("j", ("a",), method="btree")},
        unique_constraints={"u": UniqueConstraint("u", ("a",))},
        check_constraints={"c": CheckConstraint("c", "a > 0")},
    )
    tgt = table(
        indexes={
            "i": Index("i", ("a", "b"), unique=True, predicate="a > 1"),
            "k": Index("k", ("b",)),
        },
        unique_constraints={},
        check_constraints={"c": CheckConstraint("c", "a > 1")},
    )
    changes = diff_schemas(schema(src), schema(tgt))
    assert summary(changes) == expect(
        ("warning", "removed", "index", "t.j", None),
        ("warning", "added", "index", "t.k", None),
        ("warning", "changed", "index", "t.i", "columns"),
        ("warning", "changed", "index", "t.i", "unique"),
        ("warning", "changed", "index", "t.i", "predicate"),
        ("warning", "removed", "unique_constraint", "t.u", None),
        ("warning", "changed", "check_constraint", "t.c", "expression"),
    )
    by_path = {(c.path, c.attribute): c for c in changes}
    assert by_path["t.j", None].source == "(a) using btree"
    assert by_path["t.k", None].target == "(b)"
    assert by_path["t.c", "expression"].note is not None


def test_foreign_key_differences_are_errors() -> None:
    fk = ForeignKey("fk", ("a",), "p", ("id",), "CASCADE", "NO ACTION")
    src = table(foreign_keys={"fk": fk})
    assert summary(diff_schemas(schema(src), schema(table()))) == [
        ("error", "removed", "foreign_key", "t.fk", None)
    ]
    tgt = table(foreign_keys={"fk": replace(fk, on_delete="RESTRICT", ref_table="q")})
    changes = diff_schemas(schema(src), schema(tgt))
    assert summary(changes) == expect(
        ("error", "changed", "foreign_key", "t.fk", "ref_table"),
        ("error", "changed", "foreign_key", "t.fk", "on_delete"),
    )
    added = diff_schemas(schema(table()), schema(src))
    assert added[0].target == "(a) -> p(id) on delete cascade on update no action"


def test_comments_and_views_and_enums() -> None:
    src = schema(
        table(comment="a"),
        views={"v1": "x", "v2": "y", "v3": "z"},
        enums={"e1": ("a",), "e2": ("a",), "e3": ("a", "b")},
    )
    tgt = schema(
        table(comment="b"),
        views={"v1": "x", "v2": "changed", "v4": "w"},
        enums={"e1": ("a",), "e3": ("b", "a"), "e4": ("c",)},
    )
    assert summary(diff_schemas(src, tgt)) == expect(
        ("note", "changed", "table", "t", "comment"),
        ("warning", "removed", "view", "v3", None),
        ("warning", "changed", "view", "v2", "definition"),
        ("warning", "added", "view", "v4", None),
        ("warning", "removed", "enum", "e2", None),
        ("warning", "changed", "enum", "e3", "labels"),
        ("warning", "added", "enum", "e4", None),
    )


def test_name_insensitive_index_matching() -> None:
    src = table(indexes={"idx_old": Index("idx_old", ("a",), True)})
    tgt = table(indexes={"idx_new": Index("idx_new", ("a",), True)})
    assert len(diff_schemas(schema(src), schema(tgt))) == 2
    assert diff_schemas(schema(src), schema(tgt), Options(ignore_index_names=True)) == []
    different = table(indexes={"idx_new": Index("idx_new", ("a",), False)})
    changes = diff_schemas(schema(src), schema(different), Options(ignore_index_names=True))
    assert summary(changes) == expect(
        ("warning", "removed", "index", "t.idx_old", None),
        ("warning", "added", "index", "t.idx_new", None),
    )


def test_name_insensitive_matching_counts_duplicates() -> None:
    two = table(indexes={"a": Index("a", ("x",)), "b": Index("b", ("x",))})
    one = table(indexes={"c": Index("c", ("x",))})
    changes = diff_schemas(schema(two), schema(one), Options(ignore_index_names=True))
    assert summary(changes) == [("warning", "removed", "index", "t.b", None)]


def test_name_insensitive_constraint_matching() -> None:
    fk1 = ForeignKey("fk_a", ("a",), "p", ("id",))
    fk2 = ForeignKey("fk_b", ("a",), "p", ("id",))
    src = table(
        foreign_keys={"fk_a": fk1},
        unique_constraints={"u1": UniqueConstraint("u1", ("a",))},
        check_constraints={"c1": CheckConstraint("c1", "a > 0")},
    )
    tgt = table(
        foreign_keys={"fk_b": fk2},
        unique_constraints={"u2": UniqueConstraint("u2", ("a",))},
        check_constraints={"c2": CheckConstraint("c2", "a > 0")},
    )
    assert len(diff_schemas(schema(src), schema(tgt))) == 6
    assert diff_schemas(schema(src), schema(tgt), Options(ignore_constraint_names=True)) == []
    assert len(diff_schemas(schema(src), schema(tgt), Options(ignore_index_names=True))) == 6


def test_column_order_only_in_strict_mode() -> None:
    src = table(columns={"a": col("a", 1), "b": col("b", 2), "c": col("c", 3)})
    tgt = table(columns={"a": col("a", 1), "c": col("c", 2), "b": col("b", 3)})
    assert diff_schemas(schema(src), schema(tgt)) == []
    changes = diff_schemas(schema(src), schema(tgt), Options(ignore_column_order=False))
    assert summary(changes) == [("note", "changed", "table", "t", "column_order")]
    assert changes[0].source == ["a", "b", "c"]
    assert changes[0].target == ["a", "c", "b"]


def test_strict_order_ignores_added_columns() -> None:
    src = table(columns={"a": col("a", 1), "b": col("b", 2)})
    tgt = table(columns={"x": col("x", 1), "a": col("a", 2), "b": col("b", 3)})
    changes = diff_schemas(schema(src), schema(tgt), Options(ignore_column_order=False))
    assert summary(changes) == [("error", "added", "column", "t.x", None)]


def test_table_filters() -> None:
    a = schema(table("keep"), table("alembic_version"), table("tmp_1"))
    b = schema()
    assert [c.path for c in diff_schemas(a, b)] == ["keep", "tmp_1"]
    only = Options(include_tables=("keep*",))
    assert [c.path for c in diff_schemas(a, b, only)] == ["keep"]
    none = Options(exclude_tables=())
    assert len(diff_schemas(a, b, none)) == 3
    assert not table_selected("tmp_1", Options(exclude_tables=("tmp_*",)))
    assert table_selected("TMP_1", Options(exclude_tables=("tmp_*",)))


def test_dialect_mismatch_is_rejected() -> None:
    with pytest.raises(DialectMismatchError, match=r"postgresql.*mysql"):
        diff_schemas(schema(dialect="postgresql"), schema(dialect="mysql"))


def test_ordering_is_deterministic() -> None:
    a = schema(table("z"), table("a"), views={"v": "1"})
    b = schema(views={"v": "2"})
    paths = [c.path for c in diff_schemas(a, b)]
    assert paths == ["a", "z", "v"]


def test_exceeds_and_counts() -> None:
    changes = [
        Change("added", "table", "a", Severity.ERROR),
        Change("added", "index", "a.i", Severity.WARNING, "a"),
        Change("changed", "column", "a.c", Severity.NOTE, "a", "comment"),
    ]
    assert count_by_severity(changes) == {"error": 1, "warning": 1, "note": 1}
    assert exceeds(changes, "error")
    assert exceeds(changes[1:], "warning")
    assert not exceeds(changes[1:], "error")
    assert exceeds(changes[2:], "note")
    assert not exceeds(changes[2:], "warning")
    assert not exceeds(changes, "never")
    assert not exceeds([], "note")
    assert changes[0].to_dict()["severity"] == "error"
