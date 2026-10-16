import uuid
from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.schema import WebAnalyticsQueryModifiers

from posthog.hogql import ast

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    WebAnalyticsPreAggregatedQueryBuilder,
)

_QB = "products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder"
_READY = LazyComputationResult(ready=True, job_ids=[uuid.uuid4()])


def _runner(opted_in: bool) -> MagicMock:
    runner = MagicMock()
    runner.query.webQueryModifiers = WebAnalyticsQueryModifiers(useDimensionalTables=opted_in)
    runner.query_date_range.date_from.return_value = datetime(2026, 3, 1, tzinfo=UTC)
    runner.query_date_range.date_to.return_value = datetime(2026, 6, 1, tzinfo=UTC)
    runner.query_compare_to_date_range = None
    runner.use_v2_tables = True
    runner.query.properties = []
    return runner


class TestDimensionalReadSelection(SimpleTestCase):
    def setUp(self) -> None:
        rules = patch(f"{_QB}.team_has_property_access_rules", return_value=False)
        self.mock_rules = rules.start()
        self.addCleanup(rules.stop)

    @patch(f"{_QB}.web_bounces_dimensional_ready_jobs", return_value=_READY)
    @patch(f"{_QB}.web_stats_dimensional_ready_jobs", return_value=_READY)
    def test_opted_in_query_with_ready_data_reads_dimensional_and_filters_job_id(self, _mock_stats, _mock_bounces):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(True), {})

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

    @patch(f"{_QB}.web_bounces_dimensional_ready_jobs", return_value=_READY)
    @patch(f"{_QB}.web_stats_dimensional_ready_jobs", return_value=LazyComputationResult(ready=False, job_ids=[]))
    def test_opted_in_query_without_ready_data_falls_back_to_v2(self, _mock_stats, _mock_bounces):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(True), {})

        assert builder.stats_table == "web_pre_aggregated_stats"
        assert builder.bounces_table == "web_pre_aggregated_bounces"
        assert builder._dimensional_job_id_filter("web_pre_aggregated_stats") is None

    def test_query_without_opt_in_uses_v2(self):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(False), {})

        assert builder.stats_table == "web_pre_aggregated_stats"
        assert builder.bounces_table == "web_pre_aggregated_bounces"

    @patch(f"{_QB}.web_bounces_dimensional_ready_jobs", return_value=_READY)
    @patch(f"{_QB}.web_stats_dimensional_ready_jobs", return_value=_READY)
    def test_team_with_property_access_rules_uses_v2(self, _mock_stats, _mock_bounces):
        self.mock_rules.return_value = True
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(True), {})

        assert builder.stats_table == "web_pre_aggregated_stats"
        assert builder.bounces_table == "web_pre_aggregated_bounces"
