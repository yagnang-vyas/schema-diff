# AGENTS.md

Guidance for AI coding agents (and humans) working on SchemaDiff.

## What this project is

A read-only Python CLI that compares the schemas of two PostgreSQL or two MySQL
databases (or saved JSON snapshots) and reports drift. See `SPEC.md` for behaviour and
the decisions behind it.

## Commands

```
make install            # pip install -e ".[dev]"
make lint               # ruff check + ruff format --check
make typecheck          # mypy --strict
make test-unit          # no database needed
make db-up / db-down    # docker compose: postgres:16, mysql:8.4 on 127.0.0.1
make test-integration   # needs SCHEMADIFF_PG_URL and SCHEMADIFF_MYSQL_URL (see .env.example)
make test               # unit + integration with branch coverage (>= 90%)
make check              # lint + typecheck + test
```

## Layout

```
src/schemadiff/
  cli.py          argparse CLI, exit codes
  urls.py         URL parsing, env resolution, password masking
  inspect/        read-only catalog inspection (postgres.py, mysql.py, common.py)
  model.py        normalized schema model (frozen dataclasses)
  normalize.py    type / default / expression normalization
  snapshot.py     deterministic JSON snapshots
  diff.py         pure function (Schema, Schema, Options) -> list[Change]
  report/         text, json, markdown renderers
tests/unit/       no database
tests/integration/ real PostgreSQL and MySQL; SQL setup scripts in tests/integration/sql/
```

## Rules

- **Read-only.** Every connection is opened read-only (PostgreSQL
  `default_transaction_read_only=on`; MySQL `SET SESSION TRANSACTION READ ONLY`). Only
  catalog metadata is queried, never table data. Never run DDL or DML on a user's database.
  Test setup code uses its own separate connections.
- **Credentials.** Never print a URL with its password: use `urls.safe_url`, and pass
  every database error message through `urls.redact`. Snapshots contain no credentials and
  no host names.
- **No false positives.** Identical schemas must produce zero changes. When you add a
  field to the model, add normalization for it and an equivalent-spelling test.
- **Never weaken tests.** Fix the code, not the check. Do not skip tests or lower coverage
  thresholds. CI sets `SCHEMADIFF_REQUIRE_DB=1` so a missing database fails the run.
- **Diff stays pure.** `diff.py` does no I/O and works on model objects only.
- Style: ruff (`E,F,W,I,B,UP,SIM,RUF`), mypy strict, Python 3.11+, Conventional Commits.
