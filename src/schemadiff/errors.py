"""Exceptions that map to a user-facing message and exit code 2."""


class SchemaDiffError(Exception):
    """Base class: the message is safe to print (it never contains a password)."""


class InputError(SchemaDiffError):
    """Invalid usage or input."""


class DatabaseError(SchemaDiffError):
    """A database could not be reached or read."""


class SnapshotError(SchemaDiffError):
    """A snapshot file is unreadable, invalid or has an unsupported version."""


class DialectMismatchError(SchemaDiffError):
    """The two sides of a comparison use different database engines."""
