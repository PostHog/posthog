from __future__ import annotations

from datetime import datetime, timedelta

from unittest import TestCase

from posthog.schema import DateRange, ErrorTrackingQuery

from posthog.hogql import ast

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import build_event_where_exprs


def _collect_calls(node: ast.Expr | None, name: str) -> list[ast.Call]:
    """Walk a HogQL AST and collect every ``ast.Call`` matching ``name``."""
    found: list[ast.Call] = []

    def visit(value: object) -> None:
        if isinstance(value, ast.Call):
            if value.name == name:
                found.append(value)
            for arg in value.args:
                visit(arg)
            return
        if isinstance(value, ast.CompareOperation):
            visit(value.left)
            visit(value.right)
            return
        if isinstance(value, ast.And | ast.Or):
            for child in value.exprs:
                visit(child)
            return

    visit(node)
    return found


class TestBuildEventWhereExprs(TestCase):
    def test_search_email_fields_wrapped_in_to_string(self) -> None:
        # Regression for Float64 email columns — ClickHouse rejects ``lower(Float64)``.
        # Without ``toString`` wrap, teams whose ``properties___email`` materialized as numeric
        # blow up with ``Illegal type Float64 of argument of function lower``.
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            dateRange=DateRange(),
            orderBy="last_seen",
            volumeResolution=1,
            searchQuery="terminated",
        )
        date_from = datetime(2026, 1, 1)
        date_to = date_from + timedelta(days=1)

        exprs = build_event_where_exprs(query, date_from, date_to)

        lower_calls = _collect_calls(ast.And(exprs=exprs), "lower")
        # 6 lower(field) wrappers + 6 lower(token) literal wrappers.
        self.assertEqual(len(lower_calls), 12)

        email_field_chains: set[tuple[str, ...]] = set()
        for lower_call in lower_calls:
            inner = lower_call.args[0]
            if isinstance(inner, ast.Constant):
                continue  # lower('terminated')
            self.assertIsInstance(
                inner,
                ast.Call,
                f"expected lower() to wrap toString(...) but got {type(inner).__name__}",
            )
            assert isinstance(inner, ast.Call)
            self.assertEqual(
                inner.name,
                "toString",
                "search field must be cast to String before lower() — Float64 columns otherwise raise",
            )
            field = inner.args[0]
            self.assertIsInstance(field, ast.Field)
            assert isinstance(field, ast.Field)
            chain = tuple(str(part) for part in field.chain)
            if chain[-1] == "email":
                email_field_chains.add(chain)

        self.assertEqual(
            email_field_chains,
            {("properties", "email"), ("person", "properties", "email")},
        )
