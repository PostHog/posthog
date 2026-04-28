from unittest import TestCase

from posthog.schema import NonIntegratedConversionsColumnsSchemaNames

from posthog.hogql import ast

from products.marketing_analytics.backend.hogql_queries.non_integrated_conversions_table_query_runner import (
    NonIntegratedConversionsTableQueryRunner,
)


class TestNonIntegratedConversionsCompareTupleColumns(TestCase):
    """Regression coverage for the compare flow column-shape mismatch.

    The base runner builds two subqueries (current + previous period) and references
    `previous_period.<col>` for each column projected by the current period. When the
    previous-period subquery falls back to the empty Source + Campaign shape (e.g. because
    its conversion-goal processors got filtered out), referencing a missing alias raises
    `ResolutionError: Field <x> not found on query with alias previous_period` deep in
    HogQL type resolution. The fix swaps in NULL for any column not projected by the
    previous-period query.
    """

    maxDiff = None

    @staticmethod
    def _select(*aliases: str) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[ast.Alias(alias=alias, expr=ast.Constant(value=None)) for alias in aliases],
        )

    @staticmethod
    def _select_columns(*aliases: str) -> list[ast.Expr]:
        return [ast.Alias(alias=alias, expr=ast.Constant(value=None)) for alias in aliases]

    def test_substitutes_null_when_previous_period_missing_conversion_goal(self):
        source = NonIntegratedConversionsColumnsSchemaNames.SOURCE.value
        campaign = NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value
        goal = "Onboarded (1)"

        result = NonIntegratedConversionsTableQueryRunner._build_compare_tuple_columns(
            self._select_columns(source, campaign, goal),
            self._select(source, campaign),
        )

        tuple_by_alias: dict[str, ast.Call] = {}
        for col in result:
            assert isinstance(col, ast.Alias)
            assert isinstance(col.expr, ast.Call)
            assert col.expr.name == "tuple"
            tuple_by_alias[col.alias] = col.expr

        for shared in (source, campaign):
            current_arg, previous_arg = tuple_by_alias[shared].args
            assert isinstance(current_arg, ast.Field)
            assert current_arg.chain == ["current_period", shared]
            assert isinstance(previous_arg, ast.Field)
            assert previous_arg.chain == ["previous_period", shared]

        current_arg, previous_arg = tuple_by_alias[goal].args
        assert isinstance(current_arg, ast.Field)
        assert current_arg.chain == ["current_period", goal]
        assert isinstance(previous_arg, ast.Constant)
        assert previous_arg.value is None

    def test_uses_previous_field_when_columns_match(self):
        source = NonIntegratedConversionsColumnsSchemaNames.SOURCE.value
        campaign = NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value
        goal = "Signed up"

        result = NonIntegratedConversionsTableQueryRunner._build_compare_tuple_columns(
            self._select_columns(source, campaign, goal),
            self._select(source, campaign, goal),
        )

        for col in result:
            assert isinstance(col, ast.Alias)
            assert isinstance(col.expr, ast.Call)
            current_arg, previous_arg = col.expr.args
            assert isinstance(current_arg, ast.Field)
            assert isinstance(previous_arg, ast.Field)
            assert current_arg.chain == ["current_period", col.alias]
            assert previous_arg.chain == ["previous_period", col.alias]

    def test_handles_empty_previous_period_select(self):
        source = NonIntegratedConversionsColumnsSchemaNames.SOURCE.value
        goal_a = "Onboarded (1)"
        goal_b = "Signed up"

        empty_previous = ast.SelectQuery(select=[])

        result = NonIntegratedConversionsTableQueryRunner._build_compare_tuple_columns(
            self._select_columns(source, goal_a, goal_b),
            empty_previous,
        )

        for col in result:
            assert isinstance(col, ast.Alias)
            assert isinstance(col.expr, ast.Call)
            _, previous_arg = col.expr.args
            assert isinstance(previous_arg, ast.Constant)
            assert previous_arg.value is None
