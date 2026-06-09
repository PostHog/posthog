import uuid
from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from posthog.hogql import ast

from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    WebAnalyticsPreAggregatedQueryBuilder,
)

_QB = "products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder"


def _runner(team_id: int) -> MagicMock:
    runner = MagicMock()
    runner.team.id = team_id
    runner.query_date_range.date_from.return_value = datetime(2026, 3, 1, tzinfo=UTC)
    runner.query_date_range.date_to.return_value = datetime(2026, 6, 1, tzinfo=UTC)
    runner.query_compare_to_date_range = None
    runner.use_v2_tables = True
    runner.query.properties = []
    return runner


class TestDimensionalReadSelection(SimpleTestCase):
    @override_settings(WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS=[2])
    @patch(f"{_QB}.web_bounces_dimensional_job_ids", return_value=[uuid.uuid4()])
    @patch(f"{_QB}.web_stats_dimensional_job_ids", return_value=[uuid.uuid4()])
    def test_enrolled_team_with_ready_data_reads_dimensional_and_filters_job_id(self, _mock_stats, _mock_bounces):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(2), {})

        assert builder.stats_table == WEB_STATS_DIMENSIONAL_READ_TABLE
        assert builder.bounces_table == WEB_BOUNCES_DIMENSIONAL_READ_TABLE

        job_filter = builder._dimensional_job_id_filter(WEB_STATS_DIMENSIONAL_READ_TABLE)
        assert isinstance(job_filter, ast.CompareOperation)
        assert job_filter.op == ast.CompareOperationOp.In
        # the WHERE built by _get_filters carries the job_id filter
        where = builder._get_filters(WEB_STATS_DIMENSIONAL_READ_TABLE)
        assert isinstance(where, ast.And)
        assert any(isinstance(e, ast.CompareOperation) and e.op == ast.CompareOperationOp.In for e in where.exprs), (
            "dimensional read WHERE must include job_id IN (...)"
        )

    @override_settings(WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS=[2])
    @patch(f"{_QB}.web_bounces_dimensional_job_ids", return_value=[uuid.uuid4()])
    @patch(f"{_QB}.web_stats_dimensional_job_ids", return_value=[])
    def test_enrolled_team_without_ready_data_falls_back_to_v2(self, _mock_stats, _mock_bounces):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(2), {})

        assert builder.stats_table == "web_pre_aggregated_stats"
        assert builder.bounces_table == "web_pre_aggregated_bounces"
        assert builder._dimensional_job_id_filter("web_pre_aggregated_stats") is None

    @override_settings(WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS=[2])
    def test_unenrolled_team_uses_v2(self):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(999), {})

        assert builder.stats_table == "web_pre_aggregated_stats"
        assert builder.bounces_table == "web_pre_aggregated_bounces"
