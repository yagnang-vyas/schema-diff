"""Read-only inspection of live databases."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, Connection
from sqlalchemy.exc import SQLAlchemyError

from schemadiff.errors import DatabaseError, InputError
from schemadiff.model import Schema
from schemadiff.urls import MYSQL, POSTGRESQL, redact, safe_url

CONNECT_TIMEOUT_SECONDS = 10


def make_engine(url: URL, dialect: str) -> Engine:
    """Create an engine whose every connection is read-only."""
    if dialect == POSTGRESQL:
        return create_engine(
            url,
            connect_args={
                "options": "-c default_transaction_read_only=on",
                "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            },
        )
    engine = create_engine(url, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS})

    @event.listens_for(engine, "connect")
    def _read_only(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        finally:
            cursor.close()

    return engine


@contextmanager
def read_only_connection(url: URL, dialect: str) -> Iterator[Connection]:
    """Yield a read-only connection; the transaction is always rolled back."""
    engine = make_engine(url, dialect)
    try:
        with engine.connect() as connection:
            try:
                yield connection
            finally:
                connection.rollback()
    finally:
        engine.dispose()


def inspect_database(url: URL, dialect: str, schema: str | None) -> Schema:
    """Read the schema (PostgreSQL schema, or MySQL database) behind a URL."""
    from schemadiff.inspect import mysql, postgres

    try:
        with read_only_connection(url, dialect) as connection:
            if dialect == POSTGRESQL:
                return postgres.inspect_schema(connection, schema or "public")
            if dialect == MYSQL:
                return mysql.inspect_schema(connection, schema or url.database)
            raise InputError(f"unsupported dialect {dialect}")  # pragma: no cover
    except SQLAlchemyError as exc:
        reason = str(getattr(exc, "orig", None) or exc).strip().splitlines()[0]
        raise DatabaseError(f"cannot read {safe_url(url)}: {redact(reason)}") from None
