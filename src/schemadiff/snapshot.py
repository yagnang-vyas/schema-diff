"""Deterministic JSON snapshots of a schema.

Snapshots hold catalog metadata only: no credentials, no host names and no data.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from schemadiff import __version__
from schemadiff.errors import SnapshotError
from schemadiff.model import Schema, Table

SCHEMA_VERSION = 1
_DIALECTS = {"postgresql", "mysql"}


def captured_at_now() -> str:
    """Capture time, honouring SOURCE_DATE_EPOCH for reproducible output."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    when = (
        datetime.fromtimestamp(int(epoch), UTC) if epoch and epoch.isdigit() else datetime.now(UTC)
    )
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_dict(schema: Schema, captured_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "schemadiff", "version": __version__},
        "dialect": schema.dialect,
        "server_version": schema.server_version,
        "schema": schema.schema,
        "captured_at": captured_at,
        "tables": {k: v.to_dict() for k, v in sorted(schema.tables.items())},
        "views": dict(sorted(schema.views.items())),
        "enums": {k: list(v) for k, v in sorted(schema.enums.items())},
    }


def dumps(schema: Schema, captured_at: str) -> str:
    return json.dumps(to_dict(schema, captured_at), indent=2, sort_keys=True) + "\n"


def save(schema: Schema, path: Path, captured_at: str | None = None) -> None:
    text = dumps(schema, captured_at or captured_at_now())
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"cannot write snapshot {path}: {exc.strerror}") from None


def loads(text: str) -> Schema:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise SnapshotError("snapshot is not valid JSON") from None
    if not isinstance(data, dict):
        raise SnapshotError("snapshot must be a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SnapshotError(
            f"unsupported snapshot schema_version {version!r} (this version reads {SCHEMA_VERSION})"
        )
    if data.get("dialect") not in _DIALECTS:
        raise SnapshotError(f"snapshot has an unknown dialect {data.get('dialect')!r}")
    try:
        return Schema(
            dialect=data["dialect"],
            schema=data["schema"],
            server_version=data.get("server_version", ""),
            tables={k: Table.from_dict(k, v) for k, v in data["tables"].items()},
            views=dict(data.get("views", {})),
            enums={k: tuple(v) for k, v in data.get("enums", {}).items()},
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SnapshotError("snapshot is missing required fields or is malformed") from None


def load(path: Path) -> Schema:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot {path}: {exc.strerror}") from None
    return loads(text)
