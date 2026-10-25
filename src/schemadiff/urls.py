"""Database URL resolution and credential masking."""

from __future__ import annotations

import os
import re
from urllib.parse import quote

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from schemadiff.errors import InputError

POSTGRESQL = "postgresql"
MYSQL = "mysql"

_DRIVERS = {
    "postgresql": (POSTGRESQL, "postgresql+psycopg"),
    "postgres": (POSTGRESQL, "postgresql+psycopg"),
    "postgresql+psycopg": (POSTGRESQL, "postgresql+psycopg"),
    "mysql": (MYSQL, "mysql+pymysql"),
    "mysql+pymysql": (MYSQL, "mysql+pymysql"),
    "mariadb": (MYSQL, "mysql+pymysql"),
    "mariadb+pymysql": (MYSQL, "mysql+pymysql"),
}

_secrets: set[str] = set()
_URL_CREDENTIALS = re.compile(r"(://[^:/@\s]*:)[^@\s]*@")


def parse_url(raw: str) -> tuple[URL, str]:
    """Parse a SQLAlchemy URL into (URL with a supported driver, dialect name).

    The error messages never repeat the input, which may contain a password.
    """
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):
        raise InputError(
            "the database URL could not be parsed "
            "(expected dialect://user:password@host:port/database)"
        ) from None
    if url.password:
        register_secret(url.password)
    try:
        dialect, driver = _DRIVERS[url.drivername]
    except KeyError:
        raise InputError(
            f"unsupported database dialect '{url.drivername}' "
            "(supported: postgresql://, mysql://, mariadb://)"
        ) from None
    return url.set(drivername=driver), dialect


def resolve_url(*, env: str | None = None, url: str | None = None) -> tuple[URL, str]:
    """Resolve a connection URL from an environment variable name or a literal URL."""
    if env is not None:
        value = os.environ.get(env)
        if not value:
            raise InputError(f"environment variable {env} is not set or is empty")
        return parse_url(value)
    if url is None:
        raise InputError("no database URL given")
    return parse_url(url)


def safe_url(url: URL) -> str:
    """Render a URL with the password hidden."""
    return url.render_as_string(hide_password=True)


def register_secret(secret: str) -> None:
    """Remember a password so that `redact` removes it from any later text."""
    if secret:
        _secrets.add(secret)
        _secrets.add(quote(secret, safe=""))


def redact(text: str) -> str:
    """Remove known passwords and any `user:password@` URL credentials from text."""
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    return _URL_CREDENTIALS.sub(r"\1***@", text)
