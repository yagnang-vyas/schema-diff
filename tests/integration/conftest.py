from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from schemadiff.diff import Change
from schemadiff.urls import parse_url

SQL_DIR = Path(__file__).parent / "sql"
ENV_VARS = {"postgresql": "SCHEMADIFF_PG_URL", "mysql": "SCHEMADIFF_MYSQL_URL"}


@dataclass(frozen=True)
class Db:
    dialect: str
    url: str  # administrative URL (setup only; SchemaDiff itself reads)

    def run_script(self, script: str) -> None:
        """Apply a SQL script on a separate autocommit connection (test setup only)."""
        url, _ = parse_url(self.url)
        engine = create_engine(url, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as connection:
                for statement in split_statements(script):
                    connection.exec_driver_sql(statement)
        finally:
            engine.dispose()

    def load(self, name: str, rename: tuple[str, str] | None = None) -> None:
        folder = "postgres" if self.dialect == "postgresql" else "mysql"
        script = (SQL_DIR / folder / name).read_text()
        if rename:
            script = script.replace(*rename)
        self.run_script(script)


def split_statements(script: str) -> list[str]:
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    parts = re.split(r";\s*(?:\n|$)", "\n".join(lines))
    return [p.strip() for p in parts if p.strip()]


def summarize(changes: list[Change]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for c in changes:
        source, target = c.source, c.target
        if c.object == "view" and c.attribute == "definition":
            assert source != target
            source = target = "<hash>"
        rows.append((c.severity.label, c.kind, c.object, c.path, c.attribute, source, target))
    return rows


@pytest.fixture(params=["postgresql", "mysql"])
def db(request: pytest.FixtureRequest) -> Db:
    dialect: str = request.param
    value = os.environ.get(ENV_VARS[dialect])
    if not value:
        if os.environ.get("SCHEMADIFF_REQUIRE_DB") == "1":
            pytest.fail(f"{ENV_VARS[dialect]} is not set but SCHEMADIFF_REQUIRE_DB=1")
        pytest.skip(f"{ENV_VARS[dialect]} is not set")
    return Db(dialect, value)


_loaded: set[str] = set()


@pytest.fixture
def drift(db: Db) -> Db:
    """The drift_source / drift_target / drift_copy schemas, created once per session."""
    if db.dialect not in _loaded:
        db.load("drift_source.sql")
        db.load("drift_target.sql")
        db.load("drift_source.sql", rename=("drift_source", "drift_copy"))
        _loaded.add(db.dialect)
    return db


@pytest.fixture
def scratch(db: Db) -> Iterator[Db]:
    """A database handle for tests that create their own throw-away schemas."""
    yield db
    for name in ("drift_renamed", "drift_order_a", "drift_order_b"):
        statement = (
            f"DROP SCHEMA IF EXISTS {name} CASCADE"
            if db.dialect == "postgresql"
            else f"DROP DATABASE IF EXISTS {name}"
        )
        db.run_script(statement + ";\n")
