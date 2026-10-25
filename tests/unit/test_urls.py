from __future__ import annotations

import pytest

from schemadiff.errors import InputError
from schemadiff.urls import parse_url, redact, resolve_url, safe_url


def test_driver_normalisation() -> None:
    assert parse_url("postgresql://u:p@h/db")[0].drivername == "postgresql+psycopg"
    assert parse_url("postgres://u:p@h/db")[1] == "postgresql"
    assert parse_url("mysql://u:p@h/db")[0].drivername == "mysql+pymysql"
    assert parse_url("mariadb://u:p@h/db")[1] == "mysql"


def test_safe_url_hides_password() -> None:
    url, _ = parse_url("postgresql://u:hunter2@h:5432/db")
    assert "hunter2" not in safe_url(url)
    assert "***" in safe_url(url)


def test_unsupported_dialect_message_does_not_echo_url() -> None:
    with pytest.raises(InputError) as info:
        parse_url("oracle://u:hunter2@h/db")
    assert "hunter2" not in str(info.value)


def test_unparseable_url_message_does_not_echo_input() -> None:
    with pytest.raises(InputError) as info:
        parse_url("not a url with hunter2")
    assert "hunter2" not in str(info.value)


def test_resolve_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SD_TEST_URL", "mysql://u:p@h/db")
    assert resolve_url(env="SD_TEST_URL")[1] == "mysql"
    monkeypatch.delenv("SD_TEST_URL")
    with pytest.raises(InputError, match="SD_TEST_URL"):
        resolve_url(env="SD_TEST_URL")


def test_resolve_requires_something() -> None:
    with pytest.raises(InputError):
        resolve_url()
    assert resolve_url(url="postgresql://u:p@h/db")[1] == "postgresql"


def test_redact_removes_registered_and_embedded_passwords() -> None:
    parse_url("postgresql://u:s3cr3t%21pw@h/db")  # registers decoded and encoded forms
    assert "s3cr3t!pw" not in redact("failed with s3cr3t!pw here")
    assert "s3cr3t%21pw" not in redact("failed with s3cr3t%21pw here")
    assert redact("see postgresql://bob:other@host/db") == "see postgresql://bob:***@host/db"
