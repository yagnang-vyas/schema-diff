"""MySQL catalog inspection (read-only), via information_schema."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from schemadiff.errors import InputError
from schemadiff.inspect.common import rank_columns, required_text
from schemadiff.inspect.common import text as to_text
from schemadiff.model import CheckConstraint, Column, ForeignKey, Index, Schema, Table
from schemadiff.normalize import (
    hash_definition,
    normalize_default,
    normalize_expression,
    normalize_type,
)
from schemadiff.urls import MYSQL

_NUMERIC_TYPES = {
    "tinyint",
    "smallint",
    "mediumint",
    "int",
    "bigint",
    "decimal",
    "float",
    "double",
    "bit",
}

_ON_UPDATE = re.compile(r"on update (.+)$")

_TABLES = text(
    """
    select table_name as name, table_comment as comment
    from information_schema.tables
    where table_schema = :schema and table_type = 'BASE TABLE'
    order by table_name
    """
)

_COLUMNS = text(
    """
    select table_name as table_name, column_name as name, column_type as type,
           data_type as data_type, is_nullable as nullable, column_default as default_value,
           extra as extra, generation_expression as generation,
           collation_name as collation, character_set_name as charset,
           column_comment as comment
    from information_schema.columns
    where table_schema = :schema
    order by table_name, ordinal_position
    """
)

_INDEXES = text(
    """
    select table_name as table_name, index_name as name, seq_in_index as seq,
           column_name as column_name, expression as expression, sub_part as sub_part,
           collation as sort, non_unique as non_unique, index_type as method
    from information_schema.statistics
    where table_schema = :schema
    order by table_name, index_name, seq_in_index
    """
)

_FOREIGN_KEYS = text(
    """
    select k.table_name as table_name, k.constraint_name as name,
           k.column_name as column_name, k.referenced_table_schema as ref_schema,
           k.referenced_table_name as ref_table, k.referenced_column_name as ref_column,
           r.delete_rule as on_delete, r.update_rule as on_update
    from information_schema.key_column_usage k
    join information_schema.referential_constraints r
      on r.constraint_schema = k.constraint_schema
     and r.constraint_name = k.constraint_name
     and r.table_name = k.table_name
    where k.table_schema = :schema and k.referenced_table_name is not null
    order by k.table_name, k.constraint_name, k.ordinal_position
    """
)

_CHECKS = text(
    """
    select tc.table_name as table_name, cc.constraint_name as name,
           cc.check_clause as expression
    from information_schema.check_constraints cc
    join information_schema.table_constraints tc
      on tc.constraint_schema = cc.constraint_schema
     and tc.constraint_name = cc.constraint_name
     and tc.constraint_type = 'CHECK'
    where cc.constraint_schema = :schema
    order by tc.table_name, cc.constraint_name
    """
)

_VIEWS = text(
    """
    select table_name as name, view_definition as definition
    from information_schema.views
    where table_schema = :schema
    order by table_name
    """
)


def _column_default(row: Any) -> str | None:
    value = to_text(row.default_value)
    extra = required_text(row.extra).lower()
    on_update = _ON_UPDATE.search(extra)
    if value is None:
        default = None
    elif "default_generated" in extra or str(row.data_type).lower() in _NUMERIC_TYPES:
        # an expression such as CURRENT_TIMESTAMP or (uuid()), or a numeric literal
        default = normalize_default(MYSQL, value)
    else:
        default = "'" + value.replace("'", "''") + "'"  # string literal
    if on_update:
        default = f"{default or ''} on update {normalize_expression(MYSQL, on_update.group(1))}"
        default = default.strip()
    return default


def inspect_schema(connection: Connection, schema: str | None) -> Schema:
    if not schema:
        raise InputError("no MySQL database selected: put it in the URL or pass --schema")
    params: dict[str, Any] = {"schema": schema}
    exists = connection.execute(
        text("select 1 from information_schema.schemata where schema_name = :schema"), params
    ).first()
    if exists is None:
        raise InputError(f"MySQL database '{schema}' does not exist or is not accessible")
    version = required_text(connection.execute(text("select version()")).scalar()).split("-")[0]

    table_comments = {
        row.name: to_text(row.comment) or None for row in connection.execute(_TABLES, params)
    }
    raw_columns = [
        r for r in connection.execute(_COLUMNS, params) if r.table_name in table_comments
    ]
    columns: dict[str, dict[str, Column]] = {name: {} for name in table_comments}
    ranks = {
        name: rank_columns([r.name for r in raw_columns if r.table_name == name])
        for name in table_comments
    }
    for row in raw_columns:
        extra = required_text(row.extra).lower()
        generation = to_text(row.generation)
        if generation:  # information_schema backslash-escapes quotes in this column only
            generation = generation.replace("\\'", "'")
        generated = None
        default = None
        if "generated" in extra and "default_generated" not in extra and generation:
            generated = normalize_expression(MYSQL, generation)
        else:
            default = _column_default(row)
        collation = to_text(row.collation)
        columns[row.table_name][row.name] = Column(
            name=row.name,
            position=ranks[row.table_name][row.name],
            type=normalize_type(MYSQL, required_text(row.type)),
            nullable=required_text(row.nullable).upper() == "YES",
            default=default,
            identity="auto_increment" in extra,
            generated=generated,
            collation=collation,
            charset=to_text(row.charset) if collation else None,
            comment=to_text(row.comment) or None,
        )

    primary_keys: dict[str, list[str]] = {}
    grouped: dict[tuple[str, str], list[Any]] = {}
    for row in connection.execute(_INDEXES, params):
        if row.table_name not in table_comments:
            continue
        grouped.setdefault((row.table_name, row.name), []).append(row)
    indexes: dict[str, dict[str, Index]] = {name: {} for name in table_comments}
    for (table_name, index_name), parts in grouped.items():
        if index_name == "PRIMARY":
            primary_keys[table_name] = [p.column_name for p in parts]
            continue
        keys: list[str] = []
        for part in parts:
            if part.column_name is not None:
                key = normalize_expression(MYSQL, f"`{part.column_name}`")
                if part.sub_part:
                    key += f"({part.sub_part})"
            else:
                key = normalize_expression(MYSQL, required_text(part.expression))
            if part.sort == "D":
                key += " desc"
            keys.append(key)
        method = required_text(parts[0].method).lower() or None
        indexes[table_name][index_name] = Index(
            name=index_name,
            columns=tuple(keys),
            unique=not parts[0].non_unique,
            predicate=None,
            method=method,
        )

    fk_parts: dict[tuple[str, str], list[Any]] = {}
    for row in connection.execute(_FOREIGN_KEYS, params):
        if row.table_name in table_comments:
            fk_parts.setdefault((row.table_name, row.name), []).append(row)
    foreign_keys: dict[str, dict[str, ForeignKey]] = {name: {} for name in table_comments}
    for (table_name, fk_name), parts in fk_parts.items():
        first = parts[0]
        ref_table = first.ref_table
        if first.ref_schema != schema:
            ref_table = f"{first.ref_schema}.{first.ref_table}"
        foreign_keys[table_name][fk_name] = ForeignKey(
            name=fk_name,
            columns=tuple(p.column_name for p in parts),
            ref_table=ref_table,
            ref_columns=tuple(p.ref_column for p in parts),
            on_delete=str(first.on_delete).upper(),
            on_update=str(first.on_update).upper(),
        )

    checks: dict[str, dict[str, CheckConstraint]] = {name: {} for name in table_comments}
    for row in connection.execute(_CHECKS, params):
        if row.table_name in table_comments:
            checks[row.table_name][row.name] = CheckConstraint(
                row.name, normalize_expression(MYSQL, required_text(row.expression))
            )

    tables = {
        name: Table(
            name=name,
            columns=columns[name],
            primary_key=tuple(primary_keys.get(name, ())),
            indexes=indexes[name],
            foreign_keys=foreign_keys[name],
            check_constraints=checks[name],
            comment=comment,
        )
        for name, comment in table_comments.items()
    }
    qualifier = re.compile(rf"`{re.escape(schema)}`\.")
    views = {
        row.name: hash_definition(MYSQL, qualifier.sub("", required_text(row.definition)))
        for row in connection.execute(_VIEWS, params)
    }
    return Schema(dialect=MYSQL, schema=schema, server_version=version, tables=tables, views=views)
