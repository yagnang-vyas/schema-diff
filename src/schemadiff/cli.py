"""Command line interface and exit codes.

Exit codes: 0 no changes at or above --fail-on, 1 drift found, 2 usage / connection /
input error, 130 interrupted, 141 output pipe closed early.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from schemadiff import __version__, snapshot
from schemadiff.diff import DEFAULT_EXCLUDES, Options, diff_schemas, exceeds
from schemadiff.errors import SchemaDiffError
from schemadiff.inspect import inspect_database
from schemadiff.model import Schema
from schemadiff.report import FORMATS, SideInfo, render
from schemadiff.urls import redact, resolve_url

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130
EXIT_PIPE = 141

_URL_WARNING = (
    "warning: database URLs on the command line can leak through shell history and "
    "process listings; prefer --{side}-env VAR"
)


_SNAPSHOT_URL_WARNING = _URL_WARNING.format(side="X").replace("--X-env", "--env")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _add_side(parser: argparse.ArgumentParser, side: str) -> None:
    group = parser.add_argument_group(f"{side} (choose one)")
    exclusive = group.add_mutually_exclusive_group(required=True)
    exclusive.add_argument(
        f"--{side}-env",
        metavar="VAR",
        help=f"environment variable holding the {side} SQLAlchemy URL (recommended)",
    )
    exclusive.add_argument(
        f"--{side}",
        dest=f"{side}_url",
        metavar="URL",
        help=f"{side} database URL (leaks via shell history; prefer --{side}-env)",
    )
    exclusive.add_argument(
        f"--{side}-snapshot", metavar="FILE", help=f"{side} schema snapshot (JSON)"
    )
    group.add_argument(
        f"--{side}-schema",
        metavar="NAME",
        help=f"schema / database for the {side} only (overrides --schema)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schemadiff",
        allow_abbrev=False,
        description="Report schema drift between two PostgreSQL or MySQL databases or snapshots.",
    )
    parser.add_argument("--version", action="version", version=f"schemadiff {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    compare = sub.add_parser("compare", help="compare two schemas and report drift")
    _add_side(compare, "source")
    _add_side(compare, "target")
    compare.add_argument(
        "--schema",
        metavar="NAME",
        help="PostgreSQL schema (default: public) or MySQL database (default: from the URL)",
    )
    compare.add_argument(
        "--include-tables", type=_csv, default=(), metavar="GLOB,...", help="only these tables"
    )
    compare.add_argument(
        "--exclude-tables",
        type=_csv,
        default=DEFAULT_EXCLUDES,
        metavar="GLOB,...",
        help="skip these tables (default: " + ",".join(DEFAULT_EXCLUDES) + "; replaces default)",
    )
    compare.add_argument("--ignore-index-names", action="store_true")
    compare.add_argument("--ignore-constraint-names", action="store_true")
    order = compare.add_mutually_exclusive_group()
    order.add_argument(
        "--ignore-column-order", dest="strict_column_order", action="store_false", default=False
    )
    order.add_argument(
        "--strict-column-order",
        dest="strict_column_order",
        action="store_true",
        help="report column order differences as notes (default: ignored)",
    )
    compare.add_argument("--format", choices=FORMATS, default="text")
    compare.add_argument(
        "--fail-on",
        choices=("error", "warning", "note", "never"),
        default="warning",
        help="lowest severity that makes the exit code 1 (default: warning)",
    )

    snap = sub.add_parser("snapshot", help="write a deterministic JSON snapshot of a schema")
    source = snap.add_mutually_exclusive_group(required=True)
    source.add_argument("--env", metavar="VAR", help="environment variable holding the URL")
    source.add_argument("--url", metavar="URL", help="database URL (prefer --env)")
    snap.add_argument("--schema", metavar="NAME", help="PostgreSQL schema or MySQL database")
    snap.add_argument("-o", "--output", metavar="FILE", required=True, type=Path)
    return parser


def _load_side(
    side: str, args: argparse.Namespace, default_schema: str | None
) -> tuple[Schema, SideInfo]:
    env = getattr(args, f"{side}_env")
    url = getattr(args, f"{side}_url")
    snapshot_path = getattr(args, f"{side}_snapshot")
    if snapshot_path is not None:
        schema = snapshot.load(Path(snapshot_path))
        return schema, SideInfo.of(f"snapshot {Path(snapshot_path).name}", schema)
    if url is not None:
        print(_URL_WARNING.format(side=side), file=sys.stderr)
    parsed, dialect = resolve_url(env=env, url=url)
    schema_name = getattr(args, f"{side}_schema") or default_schema
    schema = inspect_database(parsed, dialect, schema_name)
    label = f"env {env}" if env else "command-line URL"
    return schema, SideInfo.of(label, schema)


def _compare(args: argparse.Namespace) -> int:
    source, source_info = _load_side("source", args, args.schema)
    target, target_info = _load_side("target", args, args.schema)
    options = Options(
        ignore_index_names=args.ignore_index_names,
        ignore_constraint_names=args.ignore_constraint_names,
        ignore_column_order=not args.strict_column_order,
        include_tables=args.include_tables,
        exclude_tables=args.exclude_tables,
    )
    changes = diff_schemas(source, target, options)
    _write(render(args.format, changes, source_info, target_info))
    return EXIT_DRIFT if exceeds(changes, args.fail_on) else EXIT_OK


def _snapshot(args: argparse.Namespace) -> int:
    if args.url is not None:
        print(_SNAPSHOT_URL_WARNING, file=sys.stderr)
    parsed, dialect = resolve_url(env=args.env, url=args.url)
    schema = inspect_database(parsed, dialect, args.schema)
    snapshot.save(schema, args.output)
    print(
        f"wrote snapshot of {schema.dialect} schema '{schema.schema}' "
        f"({len(schema.tables)} tables) to {args.output}"
    )
    sys.stdout.flush()
    return EXIT_OK


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits with status 2 on usage errors
    try:
        return _compare(args) if args.command == "compare" else _snapshot(args)
    except SchemaDiffError as exc:
        print(f"error: {redact(str(exc))}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        # Point stdout at devnull so the interpreter does not complain again at exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return EXIT_PIPE
    except Exception as exc:
        print(f"error: unexpected {type(exc).__name__}: {redact(str(exc))}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
