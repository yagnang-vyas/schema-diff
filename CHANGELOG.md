# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - Unreleased

### Added
- `schemadiff compare` and `schemadiff snapshot` commands for PostgreSQL 12+ and MySQL 8.0+.
- Read-only catalog inspection of tables, columns, primary keys, indexes, unique, foreign
  key and check constraints, views and PostgreSQL enums.
- Type, default and expression normalization so identical schemas yield zero changes.
- Deterministic JSON snapshots (`schema_version` 1) with no credentials or host names.
- Text, Markdown and JSON reports; severities `error`, `warning`, `note`.
- Options: `--schema`, `--source-schema`, `--target-schema`, table include / exclude globs,
  `--ignore-index-names`, `--ignore-constraint-names`, `--strict-column-order`, `--fail-on`.
- CI exit codes: 0, 1, 2, 130, 141.
- Password masking on every output and error path.
