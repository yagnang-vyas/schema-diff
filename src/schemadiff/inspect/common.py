"""Helpers shared by the engine-specific inspectors."""

from __future__ import annotations

from typing import Any


def text(value: Any) -> str | None:
    """Coerce a driver value to str (some drivers return bytes for catalog text)."""
    if value is None:
        return None
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8")
    return str(value)


def required_text(value: Any) -> str:
    result = text(value)
    return "" if result is None else result


def rank_columns(names_in_order: list[str]) -> dict[str, int]:
    """1-based rank of each column, so dropped columns leave no gaps."""
    return {name: i for i, name in enumerate(names_in_order, start=1)}
