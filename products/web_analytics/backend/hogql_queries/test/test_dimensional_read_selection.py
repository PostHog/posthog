import uuid
from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import WebAnalyticsPreComputeStrategy, WebAnalyticsQueryModifiers

from posthog.hogql import ast

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    WebAnalyticsPreAggregatedQueryBuilder,
)

_QB = "products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder"


def _runner(opted_in: bool) -> MagicMock:
    runner = MagicMock()
    runner.query.webQueryModifiers = WebAnalyticsQueryModifiers(useDimensionalTables=opted_in)
    runner.query_date_range.date_from.return_value = datetime(2026, 3, 1, tzinfo=UTC)
    runner.query_date_range.date_to.return_value = datetime(2026, 6, 1, tzinfo=UTC)
    runner.query_compare_to_date_range = None
    runner.use_v2_tables = True
    runner.query.properties = []
    return runner


_STATS_COMPUTED_AT = datetime(2026, 6, 1, 10, tzinfo=UTC)
_BOUNCES_COMPUTED_AT = datetime(2026, 6, 1, 9, tzinfo=UTC)
_NOT_READY = LazyComputationResult(ready=False, job_ids=[])


def _ready(computed_at: datetime) -> LazyComputationResult:
    return LazyComputationResult(ready=True, job_ids=[uuid.uuid4()], computed_at=computed_at)


class TestDimensionalReadSelection(SimpleTestCase):
    @patch(f"{_QB}.team_has_property_access_rules", return_value=False)
    @patch(f"{_QB}.web_bounces_dimensional_ready_jobs", return_value=_ready(_BOUNCES_COMPUTED_AT))
    @patch(f"{_QB}.web_stats_dimensional_ready_jobs", return_value=_ready(_STATS_COMPUTED_AT))
    def test_opted_in_query_with_ready_data_reads_dimensional_and_filters_job_id(
        self, _mock_stats, _mock_bounces, _mock_rules
    ):
        builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(True), {})

        assert builder.stats_table == WEB_STATS_DIMENSIONAL_READ_TABLE
        assert builder.bounces_table == WEB_BOUNCES_DIMENSIONAL_READ_TABLE
        assert builder.served_strategy() == WebAnalyticsPreComputeStrategy.DIMENSIONAL
        # The older of the two tables bounds how stale the tile can be.
        assert builder.served_computed_at() == _BOUNCES_COMPUTED_AT.isoformat()

        job_filter = builder._dimensional_job_id_filter(WEB_STATS_DIMENSIONAL_READ_TABLE)
        assert isinstance(job_filter, ast.CompareOperation)
        assert job_filter.op == ast.CompareOperationOp.In
        # the WHERE built by _get_filters carries the job_id filter
        where = builder._get_filters(WEB_STATS_DIMENSIONAL_READ_TABLE)
        assert isinstance(where, ast.And)
        assert any(isinstance(e, ast.CompareOperation) and e.op == ast.CompareOperationOp.In for e in where.exprs), (
            "dimensional read WHERE must include job_id IN (...)"
        )

    @parameterized.expand(
        [
            ("stats_not_ready", True, _NOT_READY, False),
            ("no_opt_in", False, _ready(_STATS_COMPUTED_AT), False),
            ("property_access_rules", True, _ready(_STATS_COMPUTED_AT), True),
        ]
    )
    def test_query_falls_back_to_v2(
        self, _name: str, opted_in: bool, stats_jobs: LazyComputationResult, has_rules: bool
    ):
        with (
            patch(f"{_QB}.team_has_property_access_rules", return_value=has_rules),
            patch(f"{_QB}.web_stats_dimensional_ready_jobs", return_value=stats_jobs),
            patch(f"{_QB}.web_bounces_dimensional_ready_jobs", return_value=_ready(_BOUNCES_COMPUTED_AT)),
        ):
            builder = WebAnalyticsPreAggregatedQueryBuilder(_runner(opted_in), {})

            assert builder.stats_table == "web_pre_aggregated_stats"
            assert builder.bounces_table == "web_pre_aggregated_bounces"
            assert builder._dimensional_job_id_filter("web_pre_aggregated_stats") is None
            assert builder.served_strategy() == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
            assert builder.served_computed_at() is None
