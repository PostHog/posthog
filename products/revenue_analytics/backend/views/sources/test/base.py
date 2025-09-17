"""
Base test classes for revenue analytics view sources.

This module provides common test infrastructure for testing revenue analytics
view source builders, including mixins for ClickHouse queries, snapshots,
and API testing.
"""

from typing import cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery
from products.revenue_analytics.backend.views.schemas import Schema


class RevenueAnalyticsViewSourceBaseTest(ClickhouseTestMixin, QueryMatchingTest, APIBaseTest):
    """
    Base test class for revenue analytics view source tests.

    Provides:
    - ClickHouse query testing capabilities
    - Query snapshot testing with assertQueryMatchesSnapshot
    - API testing infrastructure
    - Common test data setup patterns
    """

    def setUp(self):
        super().setUp()
        # Common setup for revenue analytics tests can go here

    def assertBuiltQueryStructure(self, built_query: BuiltQuery | None, expected_key: str, expected_prefix: str):
        """
        Assert that a BuiltQuery has the expected structure.

        Args:
            built_query: The BuiltQuery object to test
            expected_key: Expected key value
            expected_prefix: Expected prefix value
        """
        self.assertIsNotNone(built_query)

        built_query = cast(BuiltQuery, built_query)
        self.assertEqual(built_query.key, expected_key)
        self.assertEqual(built_query.prefix, expected_prefix)

    def assertQueryContainsFields(self, query: ast.Expr, schema: Schema):
        """
        Assert that a SelectQuery contains all expected fields in its select clause and that they appear in the same order.

        Args:
            query: ast.Expr object, should either be a SelectQuery or a SelectSetQuery, or else we'll raise ValueError
            schema: Schema object we should match against
        """

        queries: list[ast.SelectQuery]

        if isinstance(query, ast.SelectQuery):
            queries = [query]
        elif isinstance(query, ast.SelectSetQuery):
            queries = query.select_queries()
        else:
            raise ValueError(f"Invalid query type: {type(query)}")

        fields = list(schema.fields.keys())
        for query in queries:
            aliases = [field.alias for field in query.select if hasattr(field, "alias")]

            for expected, actual in zip(fields, aliases):
                self.assertEqual(expected, actual, f"Field mismatch: expected {expected}, got {actual}")
