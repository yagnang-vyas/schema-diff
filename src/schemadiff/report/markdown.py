"""Markdown report for pull requests and runbooks."""

from __future__ import annotations

from schemadiff import __version__
from schemadiff.diff import Change, count_by_severity
from schemadiff.report import SideInfo, display, group_name, summary_line

_MARKERS = {"added": "+", "removed": "-", "changed": "~"}


def _cell(value: str) -> str:
    return "`" + value.replace("|", "\\|").replace("\n", " ") + "`"


def _detail(change: Change) -> str:
    if change.kind == "changed":
        return f"{change.attribute}: {display(change.source)} → {display(change.target)}"
    return display(change.target if change.kind == "added" else change.source)


def render(changes: list[Change], source: SideInfo, target: SideInfo) -> str:
    counts = count_by_severity(changes)
    lines = [
        "# SchemaDiff report",
        "",
        f"- **Source:** {source.describe()}",
        f"- **Target:** {target.describe()}",
        f"- **Tool:** schemadiff {__version__}",
        "",
        "## Summary",
        "",
    ]
    if not changes:
        lines += ["No differences found.", ""]
        return "\n".join(lines)
    lines += [
        "| Severity | Count |",
        "| --- | ---: |",
        f"| error | {counts['error']} |",
        f"| warning | {counts['warning']} |",
        f"| note | {counts['note']} |",
        "",
        summary_line(changes),
        "",
    ]
    current: str | None = None
    for change in changes:
        group = group_name(change)
        if group != current:
            if current is not None:
                lines.append("")
            current = group
            lines += [f"## `{group}`", "", "| | Severity | Object | Path | Change |"]
            lines.append("| --- | --- | --- | --- | --- |")
        detail = _detail(change)
        lines.append(
            f"| {_MARKERS[change.kind]} | {change.severity.label} | {change.object} | "
            f"{_cell(change.path)} | {_cell(detail) if detail != '(none)' else ''} |"
        )
    notes = sorted({c.note for c in changes if c.note})
    if notes:
        lines.append("")
        lines += [f"> Note: {note}." for note in notes]
    return "\n".join(lines) + "\n"
