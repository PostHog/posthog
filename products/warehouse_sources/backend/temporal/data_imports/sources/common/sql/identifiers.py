"""Identifier quoting and allowlist validation for SQL-based sources.

The single place where *unparameterized* strings (schema / table / column
names) are allowed to reach a SQL query. Every SQL source must go through
an `IdentifierQuoter` implementation so the allowlist check is uniform and
cannot be bypassed by subclasses. The allowlist is strict (alphanumeric,
`_`, `-`, `.`, `$`, `@`) — anything else raises `InvalidIdentifierError`.

The allowlist is derived from today's `mysql._sanitize_identifier` (the
only driver that already validated identifiers) but is intentionally a
superset: the old MySQL helper rejected identifiers that started with a
digit followed by letters (e.g. `"23abc"`), whereas this allowlist accepts
any mix of `_ALLOWED_CHARACTERS`. Quoted MySQL identifiers legitimately
allow digit prefixes, and every other SQL dialect we target treats quoted
identifiers as opaque strings — so the widening is a correctness
improvement rather than a behavior regression.
"""

from __future__ import annotations

import re
from typing import Protocol


class InvalidIdentifierError(ValueError):
    """Raised when an identifier fails the allowlist check.

    Subclasses `ValueError` so existing callers that catch `ValueError`
    (`mysql._sanitize_identifier` raised plain `ValueError`) keep working.
    """


_ALLOWED_EXTRA_CHARS = set("._-$@")
_ALL_DIGITS = re.compile(r"^\d+$")


def _validate_identifier(identifier: str) -> None:
    """Allowlist check shared by every concrete quoter.

    Accepts: alphanumeric plus `.`, `_`, `-`, `$`, `@`. An identifier that
    is nothing but digits is also allowed (matches today's MySQL behavior
    where `"851"` is quoted verbatim). Anything else — whitespace, a
    semicolon, a quote character, a NUL byte — raises.
    """
    if not identifier:
        raise InvalidIdentifierError("Identifier may not be empty")

    if _ALL_DIGITS.match(identifier):
        return

    for ch in identifier:
        if ch.isalnum() or ch in _ALLOWED_EXTRA_CHARS:
            continue
        raise InvalidIdentifierError(f"Invalid SQL identifier: {identifier!r}")


class IdentifierQuoter(Protocol):
    """Driver-specific quoting of a validated identifier.

    Subclasses implement the quoting style that matches their dialect
    (backticks for MySQL, double-quotes for Postgres/ANSI, square brackets
    for T-SQL). `quote` MUST call `_validate_identifier` on the input before
    any quoting so a subclass cannot skip the allowlist check.
    """

    def quote(self, identifier: str) -> str: ...

    def quote_qualified(self, *parts: str) -> str:
        """Quote each part and join with '.' for a fully-qualified reference."""
        ...


class _BaseQuoter:
    """Shared implementation detail for the two concrete quoters below.

    Deliberately not exported — external callers use the `IdentifierQuoter`
    protocol, which is all the `SelectQueryBuilder` needs.
    """

    _open: str
    _close: str

    def quote(self, identifier: str) -> str:
        _validate_identifier(identifier)
        return f"{self._open}{identifier}{self._close}"

    def quote_qualified(self, *parts: str) -> str:
        if not parts:
            raise InvalidIdentifierError("quote_qualified requires at least one part")
        return ".".join(self.quote(p) for p in parts)


class BacktickIdentifierQuoter(_BaseQuoter):
    """MySQL / MariaDB / ClickHouse quoting with backticks."""

    _open = "`"
    _close = "`"


class AnsiIdentifierQuoter(_BaseQuoter):
    """ANSI SQL quoting with double-quotes (Postgres, Redshift, Snowflake)."""

    _open = '"'
    _close = '"'


class BracketIdentifierQuoter(_BaseQuoter):
    """T-SQL quoting with square brackets (MSSQL, Azure SQL Server).

    Unlike the backtick / ANSI quoters, this one does NOT use the strict
    alphanumeric allowlist. T-SQL delimited identifiers legitimately contain
    spaces, `#`, and other punctuation that the allowlist rejects (real
    SQL Server schemas have columns like `Orden#` and tables like
    `Forma Pago`), and the allowlist crashed the import on them. Square-bracket
    quoting makes any such name safe by doubling a literal `]` to `]]` — the
    same escaping SQL Server's own `QUOTENAME()` performs — so that is the
    actual safety boundary here. Control characters (which bracket-quoting
    cannot neutralise and never appear in a real identifier) are still rejected.
    """

    _open = "["
    _close = "]"

    def quote(self, identifier: str) -> str:
        if not identifier:
            raise InvalidIdentifierError("Identifier may not be empty")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in identifier):
            raise InvalidIdentifierError(f"Invalid SQL identifier: {identifier!r}")
        escaped = identifier.replace("]", "]]")
        return f"{self._open}{escaped}{self._close}"
