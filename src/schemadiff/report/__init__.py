"""Report renderers: text, JSON and Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemadiff.diff import Change, count_by_severity
from schemadiff.model import Schema

FORMATS = ("text", "json", "markdown")


@dataclass(frozen=True)
class SideInfo:
    """What a report says about one side; never contains a URL or credentials."""

    label: str
    dialect: str
    schema: str
    server_version: str

    @classmethod
    def of(cls, label: str, schema: Schema) -> SideInfo:
        return cls(label, schema.dialect, schema.schema, schema.server_version)

    def describe(self) -> str:
        engine = {"postgresql": "PostgreSQL", "mysql": "MySQL"}.get(self.dialect, self.dialect)
        version = f" {self.server_version}" if self.server_version else ""
        return f"{self.label} ({engine}{version}, schema {self.schema})"


def display(value: Any) -> str:
    """Compact rendering of an attribute value."""
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "(" + ", ".join(str(v) for v in value) + ")"
    text = str(value)
    if text.startswith("sha256:"):
        return text[:19]
    return text


def group_name(change: Change) -> str:
    if change.table is not None:
        return change.table
    return "views" if change.object == "view" else "enums"


def summary_line(changes: list[Change]) -> str:
    counts = count_by_severity(changes)
    if not changes:
        return "No differences found."
    parts = [
        f"{counts['error']} error{'s' if counts['error'] != 1 else ''}",
        f"{counts['warning']} warning{'s' if counts['warning'] != 1 else ''}",
        f"{counts['note']} note{'s' if counts['note'] != 1 else ''}",
    ]
    return f"Summary: {', '.join(parts)} ({len(changes)} changes)"


def render(fmt: str, changes: list[Change], source: SideInfo, target: SideInfo) -> str:
    from schemadiff.report import json as json_report
    from schemadiff.report import markdown, text

    if fmt == "json":
        return json_report.render(changes, source, target)
    if fmt == "markdown":
        return markdown.render(changes, source, target)
    return text.render(changes, source, target)
