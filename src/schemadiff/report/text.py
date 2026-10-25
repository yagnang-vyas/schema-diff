"""Plain-text report grouped by table."""

from __future__ import annotations

from schemadiff import __version__
from schemadiff.diff import Change
from schemadiff.report import SideInfo, display, group_name, summary_line

_MARKERS = {"added": "+", "removed": "-", "changed": "~"}


def _detail(change: Change) -> str:
    if change.kind == "changed":
        return f"{change.attribute}: {display(change.source)} -> {display(change.target)}"
    return display(change.target if change.kind == "added" else change.source)


def render(changes: list[Change], source: SideInfo, target: SideInfo) -> str:
    lines = [
        f"SchemaDiff {__version__}",
        f"  source: {source.describe()}",
        f"  target: {target.describe()}",
        "",
    ]
    current: str | None = None
    for change in changes:
        group = group_name(change)
        if group != current:
            if current is not None:
                lines.append("")
            lines.append(group)
            current = group
        detail = "" if change.kind != "changed" and _detail(change) == "(none)" else _detail(change)
        lines.append(
            f"  {_MARKERS[change.kind]} {change.severity.label:<7} "
            f"{change.object} {change.path}" + (f"  {detail}" if detail else "")
        )
    if changes:
        lines.append("")
    lines.append(summary_line(changes))
    notes = sorted({c.note for c in changes if c.note})
    for note in notes:
        lines.append(f"Note: {note}.")
    return "\n".join(lines) + "\n"
