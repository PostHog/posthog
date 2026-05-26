"""Unit tests for NonIntegratedConversionsTableQueryRunner.

These tests target the SQL shape produced by `_build_select_query` so they can run
without a Postgres/ClickHouse fixture. They call the unbound method against a stub
``self`` that carries just the config + mocked aggregator the method touches.
"""

from unittest import TestCase
from unittest.mock import Mock

from posthog.hogql import ast

from products.marketing_analytics.backend.hogql_queries.constants import UNIFIED_CONVERSION_GOALS_CTE_ALIAS
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig
from products.marketing_analytics.backend.hogql_queries.non_integrated_conversions_table_query_runner import (
    NonIntegratedConversionsTableQueryRunner,
)


def _walk_joins(select_from: ast.JoinExpr | None) -> list[ast.JoinExpr]:
    """Collect every JoinExpr in a chain, root first."""
    chain: list[ast.JoinExpr] = []
    current = select_from
    while current is not None:
        chain.append(current)
        current = current.next_join
    return chain


def _flatten_compare_ops(node: ast.Expr | None) -> list[ast.CompareOperation]:
    """Collect every CompareOperation reachable from an And/Or tree."""
    if node is None:
        return []
    if isinstance(node, ast.CompareOperation):
        return [node]
    if isinstance(node, ast.And | ast.Or):
        out: list[ast.CompareOperation] = []
        for child in node.exprs:
            out.extend(_flatten_compare_ops(child))
        return out
    return []


def _field_chain_str(node: ast.Expr) -> str:
    return ".".join(str(part) for part in node.chain) if isinstance(node, ast.Field) else ""


class TestNonIntegratedConversionsTableQueryRunnerJoinShape(TestCase):
    """Regression tests for the duplicate-campaign fix in `_build_select_query`.

    The bug: when a team configures `campaign_id` as the campaign-field match
    preference, the strict ``UCG.match_key = CC.match_key`` join only catches
    events whose ``utm_campaign`` is the numeric ID. Events for the same campaign
    whose ``utm_campaign`` is the campaign name fall through and surface in the
    Non-integrated conversions table — even though the campaign IS integrated.

    The fix joins twice (against ``campaign_name`` and ``campaign_id``) so either
    shape excludes the row, regardless of the team's preference.
    """

    def _stub_runner(self) -> Mock:
        """Build a minimal stand-in carrying the attributes `_build_select_query` reads."""
        stub = Mock(spec=NonIntegratedConversionsTableQueryRunner)
        stub.config = MarketingAnalyticsConfig()
        return stub

    def _mock_aggregator(self) -> Mock:
        aggregator = Mock()
        aggregator.get_conversion_goal_columns.return_value = {
            "conversion_0": ast.Alias(alias="conversion_0", expr=ast.Constant(value=1))
        }
        return aggregator

    def _call_build_select_query(self) -> ast.SelectQuery:
        stub = self._stub_runner()
        return NonIntegratedConversionsTableQueryRunner._build_select_query(stub, self._mock_aggregator())

    def test_left_joins_against_both_campaign_name_and_campaign_id(self):
        """Both alternate joins must be wired so a name-shaped or id-shaped utm_campaign
        match excludes the row — regardless of which side the team picked for matching."""
        query = self._call_build_select_query()

        joins = _walk_joins(query.select_from)
        # Root FROM (unified_conversion_goals) + two LEFT JOINs against campaign_costs.
        assert len(joins) == 3, f"Expected 3 join nodes (FROM + 2 LEFT JOINs), got {len(joins)}"

        root, by_name, by_id = joins
        assert isinstance(root.table, ast.Field)
        assert root.table.chain == [UNIFIED_CONVERSION_GOALS_CTE_ALIAS]

        config = MarketingAnalyticsConfig()
        for join_node in (by_name, by_id):
            assert join_node.join_type == "LEFT JOIN"
            assert isinstance(join_node.table, ast.Field)
            assert join_node.table.chain == [config.campaign_costs_cte_name]
            assert join_node.constraint is not None

        # Pull out narrowed local references so mypy doesn't lose the `is not None`
        # check across the assertion above.
        by_name_constraint = by_name.constraint
        by_id_constraint = by_id.constraint
        assert by_name_constraint is not None and by_id_constraint is not None

        by_name_targets = {_field_chain_str(op.right) for op in _flatten_compare_ops(by_name_constraint.expr)}
        by_id_targets = {_field_chain_str(op.right) for op in _flatten_compare_ops(by_id_constraint.expr)}

        # First alternate join must target CC.campaign_name; second must target CC.campaign_id.
        # Either alias on the right side proves we're matching against the *other* field
        # rather than against the strict (preference-dependent) match_key.
        assert f"{by_name.alias}.{config.campaign_field}" in by_name_targets, (
            f"by_name join should match against CC.{config.campaign_field}, got: {by_name_targets}"
        )
        assert f"{by_id.alias}.{config.id_field}" in by_id_targets, (
            f"by_id join should match against CC.{config.id_field}, got: {by_id_targets}"
        )

    def test_where_clause_excludes_matches_on_either_field(self):
        """A row only survives when *neither* alternate join finds a known campaign."""
        query = self._call_build_select_query()
        config = MarketingAnalyticsConfig()
        joins = _walk_joins(query.select_from)
        assert len(joins) == 3
        _, by_name, by_id = joins

        where_ops = _flatten_compare_ops(query.where)
        # Each null check is `alias.<campaign_field> = NULL` (HogQL-equivalent IS NULL).
        null_check_pairs = {
            (_field_chain_str(op.left).split(".")[0], _field_chain_str(op.left).split(".")[1])
            for op in where_ops
            if isinstance(op.right, ast.Constant) and op.right.value is None
        }

        assert (by_name.alias, config.campaign_field) in null_check_pairs
        assert (by_id.alias, config.campaign_field) in null_check_pairs

    def test_join_aliases_are_distinct(self):
        """Two LEFT JOINs against the same CTE must use distinct aliases or the second
        join will collide with the first in HogQL resolution."""
        query = self._call_build_select_query()
        joins = _walk_joins(query.select_from)
        assert len(joins) == 3
        _, by_name, by_id = joins
        assert by_name.alias and by_id.alias and by_name.alias != by_id.alias
