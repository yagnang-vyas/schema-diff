"""PostgreSQL catalog inspection (read-only)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from schemadiff.errors import InputError
from schemadiff.inspect.common import rank_columns, required_text
from schemadiff.inspect.common import text as to_text
from schemadiff.model import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Schema,
    Table,
    UniqueConstraint,
)
from schemadiff.normalize import (
    hash_definition,
    is_sequence_default,
    normalize_default,
    normalize_expression,
    normalize_type,
)
from schemadiff.urls import POSTGRESQL

_FK_ACTIONS = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}
_CHECK_DEF = re.compile(r"^CHECK\s*\((.*)\)(?:\s+(?:NOT VALID|NO INHERIT))*$", re.DOTALL)

_TABLES = text(
    """
    select c.relname as name, obj_description(c.oid, 'pg_class') as comment
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = :schema and c.relkind in ('r', 'p') and not c.relispartition
    order by c.relname
    """
)

_COLUMNS = text(
    """
    select c.relname as table_name, a.attname as name,
           format_type(a.atttypid, a.atttypmod) as type, a.attnotnull as not_null,
           pg_get_expr(d.adbin, d.adrelid) as default_expr,
           a.attidentity::text as identity, a.attgenerated::text as generated,
           case when a.attcollation <> t.typcollation then coll.collname end as collation,
           col_description(a.attrelid, a.attnum) as comment
    from pg_attribute a
    join pg_class c on c.oid = a.attrelid
    join pg_namespace n on n.oid = c.relnamespace
    join pg_type t on t.oid = a.atttypid
    left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
    left join pg_collation coll on coll.oid = a.attcollation
    where n.nspname = :schema and c.relkind in ('r', 'p') and not c.relispartition
      and a.attnum > 0 and not a.attisdropped
    order by c.relname, a.attnum
    """
)

_CONSTRAINTS = text(
    """
    select rel.relname as table_name, c.conname as name, c.contype::text as type,
           array(select a.attname::text
                 from unnest(c.conkey) with ordinality as k(attnum, ord)
                 join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.attnum
                 order by k.ord) as columns,
           fr.relname as ref_table, fn.nspname as ref_schema,
           array(select a.attname::text
                 from unnest(c.confkey) with ordinality as k(attnum, ord)
                 join pg_attribute a on a.attrelid = c.confrelid and a.attnum = k.attnum
                 order by k.ord) as ref_columns,
           c.confdeltype::text as on_delete, c.confupdtype::text as on_update,
           pg_get_constraintdef(c.oid, true) as definition
    from pg_constraint c
    join pg_class rel on rel.oid = c.conrelid
    join pg_namespace n on n.oid = rel.relnamespace
    left join pg_class fr on fr.oid = c.confrelid
    left join pg_namespace fn on fn.oid = fr.relnamespace
    where n.nspname = :schema and c.contype in ('p', 'u', 'f', 'c') and not rel.relispartition
    order by rel.relname, c.conname
    """
)

_INDEXES = text(
    """
    select t.relname as table_name, ic.relname as name, i.indisunique as is_unique,
           am.amname as method,
           array(select pg_get_indexdef(i.indexrelid, k, true)
                 from generate_series(1, i.indnkeyatts) as k order by k) as columns,
           i.indoption::text as options,
           pg_get_expr(i.indpred, i.indrelid) as predicate
    from pg_index i
    join pg_class ic on ic.oid = i.indexrelid
    join pg_class t on t.oid = i.indrelid
    join pg_namespace n on n.oid = t.relnamespace
    join pg_am am on am.oid = ic.relam
    where n.nspname = :schema and t.relkind in ('r', 'p') and not t.relispartition
      and not i.indisprimary
      and not exists (select 1 from pg_constraint c
                      where c.conindid = i.indexrelid and c.contype in ('p', 'u'))
    order by t.relname, ic.relname
    """
)

_VIEWS = text(
    """
    select c.relname as name, pg_get_viewdef(c.oid, true) as definition
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = :schema and c.relkind = 'v'
    order by c.relname
    """
)

_ENUMS = text(
    """
    select t.typname as name, array_agg(e.enumlabel::text order by e.enumsortorder) as labels
    from pg_type t
    join pg_enum e on e.enumtypid = t.oid
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = :schema
    group by t.typname
    order by t.typname
    """
)


def _index_key(expression: str, option: int) -> str:
    """Normalized key part with sort order; only non-default NULLS placement is spelled out."""
    key = normalize_expression(POSTGRESQL, expression)
    descending = bool(option & 1)
    nulls_first = bool(option & 2)
    if descending:
        key += " desc"
    if nulls_first and not descending:
        key += " nulls first"
    elif descending and not nulls_first:
        key += " nulls last"
    return key


def inspect_schema(connection: Connection, schema: str) -> Schema:
    params: dict[str, Any] = {"schema": schema}
    exists = connection.execute(
        text("select 1 from pg_namespace where nspname = :schema"), params
    ).first()
    if exists is None:
        raise InputError(f"PostgreSQL schema '{schema}' does not exist")
    # Resolve type and object names relative to the inspected schema, so definitions do not
    # carry a schema qualifier that would differ between two schemas.
    connection.execute(
        text("select set_config('search_path', quote_ident(:schema) || ', pg_catalog', true)"),
        params,
    )
    version = required_text(connection.execute(text("show server_version")).scalar()).split()[0]

    table_comments = {row.name: to_text(row.comment) for row in connection.execute(_TABLES, params)}
    columns: dict[str, list[Column]] = {name: [] for name in table_comments}
    raw_columns = list(connection.execute(_COLUMNS, params))
    ranks: dict[str, dict[str, int]] = {}
    for table_name in columns:
        ranks[table_name] = rank_columns(
            [r.name for r in raw_columns if r.table_name == table_name]
        )
    for row in raw_columns:
        identity = row.identity in ("a", "d")
        generated = None
        default = None
        if row.generated == "s":
            generated = normalize_expression(POSTGRESQL, row.default_expr)
        elif row.default_expr is not None and is_sequence_default(row.default_expr):
            identity = True
        else:
            default = normalize_default(POSTGRESQL, to_text(row.default_expr))
        columns[row.table_name].append(
            Column(
                name=row.name,
                position=ranks[row.table_name][row.name],
                type=normalize_type(POSTGRESQL, row.type),
                nullable=not row.not_null,
                default=default,
                identity=identity,
                generated=generated,
                collation=to_text(row.collation),
                comment=to_text(row.comment),
            )
        )

    primary_keys: dict[str, tuple[str, ...]] = {}
    uniques: dict[str, dict[str, UniqueConstraint]] = {name: {} for name in table_comments}
    foreign_keys: dict[str, dict[str, ForeignKey]] = {name: {} for name in table_comments}
    checks: dict[str, dict[str, CheckConstraint]] = {name: {} for name in table_comments}
    for row in connection.execute(_CONSTRAINTS, params):
        if row.type == "p":
            primary_keys[row.table_name] = tuple(row.columns)
        elif row.type == "u":
            uniques[row.table_name][row.name] = UniqueConstraint(row.name, tuple(row.columns))
        elif row.type == "f":
            ref_table = row.ref_table
            if row.ref_schema != schema:
                ref_table = f"{row.ref_schema}.{row.ref_table}"
            foreign_keys[row.table_name][row.name] = ForeignKey(
                name=row.name,
                columns=tuple(row.columns),
                ref_table=ref_table,
                ref_columns=tuple(row.ref_columns),
                on_delete=_FK_ACTIONS[row.on_delete],
                on_update=_FK_ACTIONS[row.on_update],
            )
        else:
            match = _CHECK_DEF.match(row.definition.strip())
            body = match.group(1) if match else row.definition
            checks[row.table_name][row.name] = CheckConstraint(
                row.name, normalize_expression(POSTGRESQL, body)
            )

    indexes: dict[str, dict[str, Index]] = {name: {} for name in table_comments}
    for row in connection.execute(_INDEXES, params):
        options = [int(o) for o in row.options.split()]
        keys = tuple(_index_key(col, options[i]) for i, col in enumerate(row.columns))
        predicate = to_text(row.predicate)
        indexes[row.table_name][row.name] = Index(
            name=row.name,
            columns=keys,
            unique=row.is_unique,
            predicate=normalize_expression(POSTGRESQL, predicate) if predicate else None,
            method=row.method,
        )

    tables = {
        name: Table(
            name=name,
            columns={c.name: c for c in columns[name]},
            primary_key=primary_keys.get(name, ()),
            indexes=indexes[name],
            unique_constraints=uniques[name],
            foreign_keys=foreign_keys[name],
            check_constraints=checks[name],
            comment=comment,
        )
        for name, comment in table_comments.items()
    }
    views = {
        row.name: hash_definition(POSTGRESQL, row.definition)
        for row in connection.execute(_VIEWS, params)
    }
    enums = {row.name: tuple(row.labels) for row in connection.execute(_ENUMS, params)}
    return Schema(
        dialect=POSTGRESQL,
        schema=schema,
        server_version=version,
        tables=tables,
        views=views,
        enums=enums,
    )
