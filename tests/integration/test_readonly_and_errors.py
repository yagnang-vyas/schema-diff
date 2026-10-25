"""Read-only enforcement and credential masking, on real databases."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from schemadiff.errors import DatabaseError, InputError
from schemadiff.inspect import inspect_database, read_only_connection
from schemadiff.urls import parse_url, register_secret
from tests.integration.conftest import Db

PASSWORD_PROBE = "Sup3r$ecret-pw!"


def test_connection_helper_can_read(drift: Db) -> None:
    url, dialect = parse_url(drift.url)
    with read_only_connection(url, dialect) as connection:
        assert connection.execute(text("select 1")).scalar() == 1


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE schemadiff_must_not_exist (id int)",
        "DROP TABLE users",
    ],
)
def test_writes_are_rejected(drift: Db, statement: str) -> None:
    url, dialect = parse_url(drift.url)
    schema = "drift_source"
    with read_only_connection(url, dialect) as connection:
        if statement.startswith("DROP"):
            statement = f"DROP TABLE {schema}.users"
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql(statement)


def test_insert_is_rejected_and_nothing_is_written(drift: Db) -> None:
    url, dialect = parse_url(drift.url)
    with read_only_connection(url, dialect) as connection, pytest.raises(DBAPIError):
        connection.exec_driver_sql("INSERT INTO drift_source.audit_log (id) VALUES (1)")
    check = drift.dialect
    assert check in ("postgresql", "mysql")
    with read_only_connection(url, dialect) as connection:
        count = connection.execute(text("select count(*) from drift_source.audit_log")).scalar()
    assert count == 0


def test_inspection_leaves_no_trace(drift: Db) -> None:
    url, dialect = parse_url(drift.url)
    inspect_database(url, dialect, "drift_source")
    with read_only_connection(url, dialect) as connection:
        tables = connection.execute(
            text(
                "select count(*) from information_schema.tables "
                "where table_name = 'schemadiff_must_not_exist'"
            )
        ).scalar()
    assert tables == 0


def test_missing_schema_is_an_input_error(db: Db) -> None:
    url, dialect = parse_url(db.url)
    with pytest.raises(InputError, match="no_such_schema"):
        inspect_database(url, dialect, "no_such_schema")


def test_connection_refused_never_leaks_the_password(db: Db) -> None:
    url, dialect = parse_url(db.url)
    broken = url.set(password=PASSWORD_PROBE, host="127.0.0.1", port=1)
    register_secret(PASSWORD_PROBE)
    with pytest.raises(DatabaseError) as info:
        inspect_database(broken, dialect, "public")
    message = str(info.value)
    assert PASSWORD_PROBE not in message
    assert "cannot read" in message


def test_wrong_password_never_leaks_the_password(db: Db) -> None:
    url, dialect = parse_url(db.url)
    broken = url.set(password=PASSWORD_PROBE)
    register_secret(PASSWORD_PROBE)
    with pytest.raises(DatabaseError) as info:
        inspect_database(broken, dialect, "public")
    assert PASSWORD_PROBE not in str(info.value)
    assert PASSWORD_PROBE not in repr(info.value)
