# SchemaDiff

A read-only command line tool that reports **schema drift** between two PostgreSQL
databases, two MySQL databases, or saved schema snapshots.

Staging and production drift apart: a hot-fix index added by hand, a column that is
nullable in one environment, a migration applied on one side only. Nobody notices until a
query plan changes or a deploy fails. SchemaDiff compares the catalogs, normalizes away
spelling differences, and exits non-zero in CI when something really differs.

- Compares tables, columns (type, nullability, default, identity, generated expressions,
  collation, comments), primary keys, indexes, unique constraints, foreign keys, check
  constraints, views and PostgreSQL enums.
- Identical schemas produce zero changes: types, defaults and expressions are normalized.
- Read-only: every connection is read-only and only catalog metadata is read, never table data.
- Deterministic JSON snapshots, plus text, Markdown and JSON reports and CI exit codes.

## Install

From a clone (Python 3.11+):

```
pip install .            # or: make install   (editable, with dev tools)
schemadiff --version
```

## Quick start

```
cp .env.example .env
make db-up                                    # postgres:16 and mysql:8.4 on 127.0.0.1
set -a; . ./.env; set +a
psql "postgresql://schemadiff:pg_local_only_pw@127.0.0.1:55432/schemadiff" \
     -f tests/integration/sql/postgres/drift_source.sql \
     -f tests/integration/sql/postgres/drift_target.sql
mysql -h127.0.0.1 -P53306 -uroot -p"$MYSQL_ROOT_PASSWORD" < tests/integration/sql/mysql/drift_source.sql
mysql -h127.0.0.1 -P53306 -uroot -p"$MYSQL_ROOT_PASSWORD" < tests/integration/sql/mysql/drift_target.sql

# PostgreSQL: two schemas in one database
schemadiff compare --source-env SCHEMADIFF_PG_URL --target-env SCHEMADIFF_PG_URL \
    --source-schema drift_source --target-schema drift_target

# MySQL: schema = database, so use one URL per side
export SRC='mysql://root:...@127.0.0.1:53306/drift_source' TGT='mysql://root:...@127.0.0.1:53306/drift_target'
schemadiff compare --source-env SRC --target-env TGT
```

### Sample output

Real output from the bundled drift scripts (PostgreSQL 16.15, restricted to two tables):

```
$ schemadiff compare --source-env SD_PG --target-env SD_PG \
    --source-schema drift_source --target-schema drift_target --include-tables products,tags
SchemaDiff 0.1.0
  source: env SD_PG (PostgreSQL 16.15, schema drift_source)
  target: env SD_PG (PostgreSQL 16.15, schema drift_target)

products
  ~ warning index products.idx_products_name  method: btree -> hash
  ~ warning index products.idx_products_sku_price  unique: true -> false
  - warning check_constraint products.products_qty_check  qty >= 0

tags
  ~ error   primary_key tags.primary_key  columns: (id) -> (id, tag)

views
  ~ warning view active_users  definition: sha256:51f951e5e211 -> sha256:02361ef275c5

enums
  ~ warning enum status_enum  labels: (active, inactive, pending) -> (active, inactive, pending, archived)

Summary: 1 error, 5 warnings, 0 notes (6 changes)
```

MySQL 8.0.46, `--include-tables orders,tags`:

```
orders
  ~ warning column orders.id  identity: true -> false
  ~ error   column orders.note  type: varchar(100) -> varchar(200)
  ~ warning index orders.idx_orders_lower_note  columns: (lower(note)) -> (upper(note))
  ~ warning index orders.idx_orders_user_placed  columns: (user_id, placed_at) -> (placed_at, user_id)
  + warning index orders.orders_user_fkey  (user_id) using btree
  ~ error   foreign_key orders.orders_user_fkey  on_delete: CASCADE -> RESTRICT
  ~ warning check_constraint orders.orders_total_check  expression: total >= 0 -> total > 0

tags
  ~ error   primary_key tags.primary_key  columns: (id) -> (id, tag)
```

Markers: `+` only in target, `-` only in source, `~` changed. `source` is the baseline.

## Usage

```
schemadiff compare (--source-env VAR | --source URL | --source-snapshot FILE)
                   (--target-env VAR | --target URL | --target-snapshot FILE)
                   [options] [--format text|json|markdown] [--fail-on error|warning|note|never]
schemadiff snapshot (--env VAR | --url URL) -o FILE [--schema NAME]
```

| option | meaning |
| --- | --- |
| `--schema NAME` | PostgreSQL schema (default `public`) or MySQL database (default: the one in the URL) |
| `--source-schema` / `--target-schema` | per-side override, e.g. two schemas in one PostgreSQL database |
| `--include-tables GLOB,...` | only these tables (views and enums are always compared) |
| `--exclude-tables GLOB,...` | skip these; default `alembic_version`, `django_migrations`, `migrations`, `schema_migrations`, `flyway_schema_history`. Giving the option replaces the default; `""` excludes nothing |
| `--ignore-index-names` | match indexes by columns, uniqueness, predicate and method |
| `--ignore-constraint-names` | match unique, foreign key and check constraints by definition |
| `--ignore-column-order` / `--strict-column-order` | column order is ignored by default; strict mode reports a `note` |
| `--format` | `text` (default), `json`, `markdown` |
| `--fail-on` | lowest severity that gives exit code 1 (default `warning`) |

URLs are SQLAlchemy URLs: `postgresql://user:pw@host/db`, `mysql://user:pw@host/db`
(`mariadb://` is accepted but not verified). Prefer `--source-env`; URLs on the command line
trigger a warning because they leak through shell history and process listings.

### Exit codes

| code | meaning |
| --- | --- |
| 0 | no change at or above `--fail-on` |
| 1 | drift found |
| 2 | usage, connection or input error (messages never contain passwords) |
| 130 | interrupted |
| 141 | output pipe closed early (e.g. `| head`) |

### Severity

- **error**: table, column, primary key or foreign key missing or different; column type or nullability differs.
- **warning**: index, unique constraint, check constraint, default, identity, enum or view differences.
- **note**: comments, collation, charset, column order (strict mode), generated-column expressions.

See [SPEC.md](SPEC.md) for the full table and the decisions behind it.

### JSON report

```
{"format_version": 1,
 "source": {"label", "dialect", "schema", "server_version"}, "target": {...},
 "summary": {"error": n, "warning": n, "note": n, "total": n},
 "changes": [{"kind": "added|removed|changed", "object": "...", "path": "orders.idx",
              "table": "orders", "severity": "...", "attribute": "...",
              "source": ..., "target": ..., "note": ...}]}
```

Keys are sorted and the order of `changes` is deterministic.

## What is compared

| object | compared attributes |
| --- | --- |
| table | presence, comment |
| column | presence, type, nullability, default, identity / auto-increment, generated expression, collation, charset, comment |
| primary key | columns in order |
| index | columns or expressions in order (with `desc`), uniqueness, partial predicate (PostgreSQL), method |
| unique constraint | columns (PostgreSQL; in MySQL they are unique indexes) |
| foreign key | columns, referenced table and columns, `ON DELETE`, `ON UPDATE` |
| check constraint | normalized expression |
| view | hash of the normalized definition |
| enum (PostgreSQL) | labels in order |

Not compared: data, functions and procedures, triggers, grants, partitions, sequences as
objects, operator classes, deferrability, `NOT VALID` state.

## Normalization

| area | rule |
| --- | --- |
| types | lower-case canonical names: `character varying(255)` = `varchar(255)`, `int4` = `integer`, `timestamp without time zone` = `timestamp`, `timestamp with time zone` = `timestamptz`; MySQL `int(11)` = `int` (display width dropped), `tinyint(1)` stays distinct from `tinyint`, `bool` = `tinyint(1)` |
| defaults | PostgreSQL casts removed (`'active'::character varying` = `'active'`), `nextval('seq'::regclass)` becomes an identity marker, `now()` = `CURRENT_TIMESTAMP`, `NULL` = no default |
| expressions | whitespace collapsed, keyword case folded, redundant outer parentheses removed; quoted strings and identifiers are kept exactly |
| MySQL | backticks and `_utf8mb4` introducers removed; schema qualifiers removed from view definitions |

**Limits:** expressions are compared textually after normalization, so two expressions
that are equivalent but written differently (`a > 0 AND b > 0` vs `b > 0 AND a > 0`) are
reported, and the report says so. A PostgreSQL `serial` column and an identity column
compare equal.

## Using it in CI against staging

Create a read-only user. SchemaDiff only reads catalogs.

PostgreSQL:

```sql
CREATE ROLE schemadiff LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE app TO schemadiff;
GRANT USAGE ON SCHEMA public TO schemadiff;
-- the catalogs are readable by default; no table privileges are needed
```

MySQL (`information_schema` only shows objects the user has some privilege on):

```sql
CREATE USER 'schemadiff'@'%' IDENTIFIED BY '...';
GRANT SELECT ON app.* TO 'schemadiff'@'%';
```

Then in the pipeline, with the URL in a secret environment variable:

```
schemadiff compare --source-env PROD_URL --target-env STAGING_URL --fail-on warning
```

### Snapshot workflow

Commit a snapshot of production and compare new environments against it in CI, without
giving CI access to production:

```
schemadiff snapshot --env PROD_URL -o schema/prod.json          # run by someone with access
schemadiff compare --source-snapshot schema/prod.json --target-env STAGING_URL
```

Snapshots hold only the dialect, server version and catalog metadata: no credentials, no
host names, no view SQL. They are deterministic (sorted keys); set `SOURCE_DATE_EPOCH` for
a reproducible `captured_at`. Comparing snapshots of different engines is rejected.

## Security notes

- Connections are read-only (`default_transaction_read_only=on` for PostgreSQL,
  `SET SESSION TRANSACTION READ ONLY` for MySQL) and are always rolled back.
- Passwords are never printed: URLs are rendered with the password hidden and every error
  message is scrubbed of known passwords and `user:password@` fragments.
- Reports identify sides as `env VAR`, `snapshot FILE` or `command-line URL`, never by URL.

## Development

```
make install && make db-up
make check          # ruff, mypy --strict, unit + integration tests, >= 90% branch coverage
```

`make test-integration` needs `SCHEMADIFF_PG_URL` and `SCHEMADIFF_MYSQL_URL` (see
`.env.example`); CI sets `SCHEMADIFF_REQUIRE_DB=1` so missing databases fail the run.
CI runs Python 3.11 to 3.14 against `postgres:16` and `mysql:8.4` service containers.

## Limitations

- PostgreSQL 12+ and MySQL 8.0+ only. MariaDB and PostgreSQL older than 12 are untested.
- MySQL creates an index for a foreign key when none fits, and that index is reported if only one side has it.
- Expression equivalence is textual (see Normalization).
- Cross-engine comparison, migration SQL generation, procedures, grants and partitions are out of scope.

## Prior art

[migra](https://github.com/djrobstep/migra) (PostgreSQL, generates migrations, archived),
[pg-schema-diff](https://github.com/stripe/pg-schema-diff), `mysqldiff` (MySQL Utilities,
discontinued), [Atlas](https://atlasgo.io) (schema-as-code platform) and Liquibase `diff`.
SchemaDiff is a focused, read-only drift reporter for both engines with CI exit codes.

## Roadmap

Migration SQL generation, SQL Server support.

## License

MIT, see [LICENSE](LICENSE).
