"""Identifier quoting for SQL-based sources.

The single place where *unparameterized* strings (schema / table / column
names) reach a SQL query. Every SQL source goes through an
`IdentifierQuoter` implementation so quoting is uniform and a subclass
cannot bypass it.

Each quoter makes a name safe by doubling its delimiter: a literal `"`
becomes `""` (ANSI: Postgres, Redshift, Snowflake), a literal `` ` ``
becomes ` `` ` (MySQL / MariaDB / ClickHouse / BigQuery), and a literal `]`
becomes `]]` (T-SQL, the same escape `QUOTENAME()` performs). Escaping —
not an allowlist — is the safety boundary, so ordinary business column
names with spaces or punctuation (`Date Established`, `applicant profile`,
`Orden#`) import correctly. Control characters, which quoting cannot
neutralise and never appear in a real identifier, are still rejected.

Doubling the delimiter fails closed even in a dialect whose lexer does not
read a doubled delimiter as one literal character. The reported failures
are names with spaces or punctuation, which hold no delimiter, so quoting
alone makes them valid. A name that does hold the delimiter is rarer than
these: doubling turns every delimiter into a pair, so the count stays even
and each one pairs with another. An injected keyword therefore stays inside
a quoted-identifier token — the worst outcome is a query the engine
rejects, never SQL that runs. Untrusted row-filter columns also pass an
allowlist upstream (`validate_and_coerce_row_filters`).
"""

from __future__ import annotations

from typing import Protocol


class InvalidIdentifierError(ValueError):
    """Raised when an identifier cannot be safely quoted.

    Subclasses `ValueError` so callers that catch `ValueError` keep working.
    """


def _reject_control_characters(identifier: str) -> None:
    if not identifier:
        raise InvalidIdentifierError("Identifier may not be empty")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in identifier):
        raise InvalidIdentifierError(f"Invalid SQL identifier: {identifier!r}")


class IdentifierQuoter(Protocol):
    """Driver-specific quoting of an identifier."""

    def quote(self, identifier: str) -> str: ...

    def quote_qualified(self, *parts: str) -> str:
        """Quote each part and join with '.' for a fully-qualified reference."""
        ...


class _BaseQuoter:
    """Shared quoting: reject control characters, then escape the delimiter.

    Deliberately not exported — external callers use the `IdentifierQuoter`
    protocol, which is all the `SelectQueryBuilder` needs.
    """

    _open: str
    _close: str

    def quote(self, identifier: str) -> str:
        _reject_control_characters(identifier)
        escaped = identifier.replace(self._close, self._close * 2)
        return f"{self._open}{escaped}{self._close}"

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
    """T-SQL quoting with square brackets (MSSQL, Azure SQL Server)."""

    _open = "["
    _close = "]"
