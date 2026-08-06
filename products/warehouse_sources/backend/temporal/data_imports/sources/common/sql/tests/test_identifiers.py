from __future__ import annotations

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    BracketIdentifierQuoter,
    InvalidIdentifierError,
)


class TestBacktickIdentifierQuoter:
    quoter = BacktickIdentifierQuoter()

    @pytest.mark.parametrize(
        "identifier,expected",
        [
            ("mydb", "`mydb`"),
            ("my_table", "`my_table`"),
            ("851", "`851`"),
            ("$col", "`$col`"),
            ("db@prod", "`db@prod`"),
            ("a-b", "`a-b`"),
            ("a.b", "`a.b`"),
        ],
    )
    def test_accepts_allowed_identifiers(self, identifier: str, expected: str) -> None:
        assert self.quoter.quote(identifier) == expected

    @pytest.mark.parametrize(
        "identifier",
        [
            "bad;id",
            "drop table x",
            "a'b",
            'a"b',
            "a`b",
            "a\nb",
            "a b",
            "a/*b*/",
            "",
        ],
    )
    def test_rejects_unsafe_identifiers(self, identifier: str) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.quoter.quote(identifier)

    def test_quote_qualified_joins_with_dot(self) -> None:
        assert self.quoter.quote_qualified("schema", "table") == "`schema`.`table`"

    def test_quote_qualified_with_three_parts(self) -> None:
        assert self.quoter.quote_qualified("catalog", "schema", "table") == "`catalog`.`schema`.`table`"

    def test_quote_qualified_requires_at_least_one_part(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.quoter.quote_qualified()

    def test_quote_qualified_rejects_any_unsafe_part(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.quoter.quote_qualified("schema", "bad;table")


class TestAnsiIdentifierQuoter:
    quoter = AnsiIdentifierQuoter()

    def test_quotes_with_double_quotes(self) -> None:
        assert self.quoter.quote("my_table") == '"my_table"'

    def test_quote_qualified_with_double_quotes(self) -> None:
        assert self.quoter.quote_qualified("public", "users") == '"public"."users"'

    def test_rejects_sql_injection_attempt(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.quoter.quote('users"; DROP TABLE x; --')

    def test_invalid_identifier_error_is_a_value_error(self) -> None:
        """Back-compat: code catching plain ValueError still works."""
        with pytest.raises(ValueError):
            self.quoter.quote("bad;id")


class TestBracketIdentifierQuoter:
    quoter = BracketIdentifierQuoter()

    @pytest.mark.parametrize(
        "identifier,expected",
        [
            ("dbo", "[dbo]"),
            ("users", "[users]"),
            ("851", "[851]"),
            ("$col", "[$col]"),
            ("a-b", "[a-b]"),
            # T-SQL delimited identifiers accept characters the alphanumeric
            # allowlist rejects; these are all real SQL Server names.
            ("Orden#", "[Orden#]"),
            ("Forma Pago", "[Forma Pago]"),
            ("Presupuesto Vs Ejecución Mes Actual Tiendas ", "[Presupuesto Vs Ejecución Mes Actual Tiendas ]"),
            ("a[b", "[a[b]"),
            # A literal `]` is escaped by doubling, exactly like QUOTENAME().
            ("a]b", "[a]]b]"),
            ("x]; DROP TABLE foo; --", "[x]]; DROP TABLE foo; --]"),
        ],
    )
    def test_accepts_allowed_identifiers(self, identifier: str, expected: str) -> None:
        assert self.quoter.quote(identifier) == expected

    @pytest.mark.parametrize(
        "identifier",
        [
            "a\nb",
            "a\tb",
            "a\x00b",
            "",
        ],
    )
    def test_rejects_unsafe_identifiers(self, identifier: str) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.quoter.quote(identifier)

    def test_quote_qualified_escapes_closing_bracket(self) -> None:
        assert self.quoter.quote_qualified("dbo", "Orden#") == "[dbo].[Orden#]"
        assert self.quoter.quote_qualified("d]o", "t]bl") == "[d]]o].[t]]bl]"

    def test_quote_qualified_joins_with_dot(self) -> None:
        assert self.quoter.quote_qualified("dbo", "users") == "[dbo].[users]"

    def test_quote_qualified_rejects_any_unsafe_part(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.quoter.quote_qualified("dbo", "bad\ntable")
