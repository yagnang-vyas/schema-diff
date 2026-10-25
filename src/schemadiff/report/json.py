"""Stable JSON report (documented in the README)."""

from __future__ import annotations

import json

from schemadiff.diff import Change, count_by_severity
from schemadiff.report import SideInfo

FORMAT_VERSION = 1


def _side(info: SideInfo) -> dict[str, str]:
    return {
        "label": info.label,
        "dialect": info.dialect,
        "schema": info.schema,
        "server_version": info.server_version,
    }


def render(changes: list[Change], source: SideInfo, target: SideInfo) -> str:
    counts = count_by_severity(changes)
    payload = {
        "format_version": FORMAT_VERSION,
        "source": _side(source),
        "target": _side(target),
        "summary": {**counts, "total": len(changes)},
        "changes": [c.to_dict() for c in changes],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
