# SchemaDiff specification

SchemaDiff is a read-only CLI that compares two PostgreSQL or two MySQL schemas (live
databases or saved snapshots) and reports drift. This document is the behavioural
reference; `README.md` is the user guide.

## Scope

In scope (v0.1.0): tables, columns, primary keys, indexes, unique constraints, foreign
keys, check constraints, views and PostgreSQL enum types, for PostgreSQL 12+ and
MySQL 8.0+. Verified against PostgreSQL 16 and MySQL 8.4 (see README).

Non-goals: cross-engine comparison (rejected with an error), migration SQL generation,
data comparison, stored procedures and functions, grants, partitions, triggers, sequences
as standalone objects, SQL Server and Oracle.

## Comparison model

A **side** is a live database schema or a snapshot. Both sides are reduced to the same
model (`model.py`): a `Schema` holding tables (columns, primary key, indexes, unique
constraints, foreign keys, check constraints, comment), views (name to hash of the
normalized definition) and enums (name to ordered labels). `diff.diff_schemas(source,
target, options)` returns a list of `Change` objects. `source` is the baseline: a
`removed` change means "present in source, absent in target"; `added` is the reverse.

### Change

| field       | meaning                                                                         |
|-------------|---------------------------------------------------------------------------------|
| `kind`      | `added`, `removed` or `changed`                                                 |
| `object`    | `table`, `column`, `primary_key`, `index`, `unique_constraint`, `foreign_key`, `check_constraint`, `view`, `enum` |
| `path`      | `table`, `table.column`, `table.index`, ... or the view / enum name             |
| `table`     | owning table, or `null` for views and enums                                     |
| `severity`  | `error`, `warning` or `note`                                                    |
| `attribute` | the attribute that differs (`changed` only), e.g. `type`, `nullable`            |
| `source` / `target` | attribute values for `changed`; a short description for `added` / `removed` |
| `note`      | optional caveat, e.g. that an expression may be semantically equivalent         |

### Severity

| severity  | changes                                                                                      |
|-----------|----------------------------------------------------------------------------------------------|
| `error`   | table, column, primary key or foreign key added/removed; foreign key definition changed; primary key columns changed; column type or nullability changed |
| `warning` | index or unique constraint added/removed/changed; default changed; identity or generated-ness changed; check constraint added/removed/changed; enum or view added/removed/changed |
| `note`    | table or column comment; collation or charset; column order (strict mode); generated-column expression changed between two generated columns |

### Matching

Tables, columns, indexes, constraints, views and enums match by name. With
`--ignore-index-names`, indexes match by `(columns/expressions, unique, predicate, method)`.
With `--ignore-constraint-names`, unique constraints match by columns, foreign keys by
`(columns, referenced table, referenced columns, ON DELETE, ON UPDATE)` and check
constraints by normalized expression. Signature matching is multiset-based, so duplicate
indexes are counted. Table filters (`--include-tables`, `--exclude-tables`) are globs
(`fnmatch`, case-sensitive) applied to table names on both sides.

## Normalization

See `normalize.py` and the README table. Types, defaults and expressions are normalized
so that spelling differences do not produce changes; nothing semantic is rewritten.

## Exit codes

`0` no change at or above `--fail-on` (default `warning`) · `1` drift · `2` usage,
connection or input errors · `130` interrupted · `141` output pipe closed early.

## Decisions

Where the brief was ambiguous the most conservative interpretation was taken.

1. **Foreign key definition changes are errors**, not warnings: `ON DELETE` / `ON UPDATE`
   change application-visible behaviour, so they rank with a missing foreign key.
2. **Primary key**: any difference (added, removed, different columns) is an error and
   has no name, so name-ignoring options do not apply.
3. **PostgreSQL serial vs identity**: `nextval('seq'::regclass)` defaults and
   `GENERATED ... AS IDENTITY` both normalize to `identity = true` with no default,
   as the brief requires. A serial column and an identity column therefore compare equal.
4. **Constraint-backed indexes are not listed as indexes.** PostgreSQL primary-key and
   unique-constraint indexes appear only as the constraint. In MySQL every unique key is
   an index, so MySQL unique constraints are reported as unique `index` objects and the
   `unique_constraint` object only exists for PostgreSQL.
5. **Column order** is not compared by default. In strict mode a single `note`
   (`table`, attribute `column_order`) compares the relative order of columns present on
   both sides, so one added column does not make every later column look moved.
   `Column.position` is a rank without gaps, not the catalog ordinal.
6. **Expressions are compared textually after normalization.** A differing check
   constraint is a `warning` whose `note` explains it may be semantically equivalent.
7. **Views** are compared by a SHA-256 of the whitespace- and case-normalized definition,
   with the inspected schema name stripped, so snapshots never contain SQL text.
8. **Default table excludes** (`alembic_version`, `django_migrations`, `migrations`,
   `schema_migrations`, `flyway_schema_history`) are replaced, not extended, when
   `--exclude-tables` is given. Pass `--exclude-tables ""` to compare everything.
   Filters apply to tables only, not views or enums.
9. **`--schema`** applies to both sides. For MySQL it names the database; without it the
   database in the URL is used. For PostgreSQL the default is `public`. It is ignored for
   snapshot sides.
10. **Partitions**: PostgreSQL partition children are skipped; the partitioned parent is
    compared. Partitioning itself is out of scope.
11. **Collation**: PostgreSQL reports a column collation only when it differs from the type
    default. MySQL reports the column collation and charset for string columns.
12. **Server version and schema name** are recorded in snapshots but never compared.
13. **MariaDB** URLs are accepted and use the MySQL inspector, but MariaDB is not part of the
    verified matrix.
14. **Read-only enforcement** uses `default_transaction_read_only=on` (PostgreSQL) and
    `SET SESSION TRANSACTION READ ONLY` on every new MySQL connection, which is the
    session-wide form of `START TRANSACTION READ ONLY`. Every connection is rolled back,
    never committed.
15. **Snapshot timestamps** use UTC and honour `SOURCE_DATE_EPOCH` for reproducible files.

## Field sources

Everything is read from the system catalogs with engine-specific queries. The SQLAlchemy
inspector is not used: it does not expose generated expressions, identity, index methods,
partial-index predicates, per-column collations, view definitions or enum labels
consistently across both engines, and a single query path per engine is easier to verify.

| field                      | PostgreSQL                                                              | MySQL                                                      |
|----------------------------|-------------------------------------------------------------------------|------------------------------------------------------------|
| tables, table comment      | `pg_class` (`relkind in ('r','p')`), `obj_description`                  | `information_schema.TABLES` (`BASE TABLE`)                 |
| column name, type          | `pg_attribute`, `format_type()`                                         | `information_schema.COLUMNS.COLUMN_TYPE`                   |
| nullable                   | `attnotnull`                                                            | `IS_NULLABLE`                                              |
| default                    | `pg_attrdef` via `pg_get_expr()`                                        | `COLUMN_DEFAULT`, `EXTRA` (`DEFAULT_GENERATED`)            |
| identity / auto-increment  | `attidentity`, `nextval()` default                                      | `EXTRA` contains `auto_increment`                          |
| generated expression       | `attgenerated` + default expression                                     | `GENERATION_EXPRESSION`                                    |
| collation, charset         | `attcollation` when not the type default                                | `COLLATION_NAME`, `CHARACTER_SET_NAME`                     |
| column comment             | `col_description()`                                                     | `COLUMN_COMMENT`                                           |
| primary key                | `pg_constraint` (`p`)                                                   | `STATISTICS` where `INDEX_NAME = 'PRIMARY'`                |
| indexes                    | `pg_index`, `pg_am`, `pg_get_indexdef(oid, k, true)`, `indpred`, `indoption` | `STATISTICS` (`EXPRESSION`, `SUB_PART`, `COLLATION`, `INDEX_TYPE`) |
| unique constraints         | `pg_constraint` (`u`)                                                   | (unique indexes, see decision 4)                           |
| foreign keys               | `pg_constraint` (`f`), `confdeltype`, `confupdtype`                     | `KEY_COLUMN_USAGE`, `REFERENTIAL_CONSTRAINTS`              |
| check constraints          | `pg_get_constraintdef()` (`c`)                                          | `CHECK_CONSTRAINTS`, `TABLE_CONSTRAINTS`                   |
| views                      | `pg_get_viewdef()`                                                      | `information_schema.VIEWS.VIEW_DEFINITION`                 |
| enum labels                | `pg_enum` ordered by `enumsortorder`                                    | inline in the column type (`enum('a','b')`)                |
| server version             | `SHOW server_version`                                                   | `SELECT VERSION()`                                         |

## Security

- Connections are read-only; only catalog metadata is queried.
- URLs are accepted from environment variables (recommended) or the command line (with a
  warning). Passwords are hidden with `render_as_string(hide_password=True)`, and every
  database error message is passed through `urls.redact`, which removes known passwords
  and `user:password@` fragments.
- Snapshots contain the dialect and server version only: no credentials and no host names.
