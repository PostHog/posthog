import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import time_machine
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import WebAnalyticsQueryModifiers

from posthog.hogql import ast

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    DimensionalJobIds,
    dimensional_job_ids,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_read import (
    DimensionalStatsTableQueryBuilder,
    ready_dimensional_job_ids,
)

_READ = "products.web_analytics.backend.hogql_queries.web_dimensional_read"
_PRECOMPUTE = "products.web_analytics.backend.hogql_queries.web_dimensional_precompute"
_STATS_IDS = [uuid.uuid4()]
_BOUNCES_IDS = [uuid.uuid4()]
_JOB_IDS = DimensionalJobIds(stats=_STATS_IDS, bounces=_BOUNCES_IDS)
_NEW_YORK = ZoneInfo("America/New_York")


def _runner(opted_in: bool | None, compare_from: datetime | None = None) -> MagicMock:
    runner = MagicMock()
    runner.team.pk = 1
    runner.query.webQueryModifiers = (
        None if opted_in is None else WebAnalyticsQueryModifiers(useDimensionalTables=opted_in)
    )
    runner.query.properties = []
    # A project-local range: the current day in New York ends after the UTC now below.
    runner.query_date_range.date_from.return_value = datetime(2026, 3, 1, tzinfo=_NEW_YORK)
    runner.query_date_range.date_to.return_value = datetime(2026, 3, 31, 23, 59, 59, tzinfo=_NEW_YORK)
    if compare_from is None:
        runner.query_compare_to_date_range = None
    else:
        runner.query_compare_to_date_range.date_from.return_value = compare_from
    return runner


def _result(ready: bool, job_ids: list[uuid.UUID]) -> LazyComputationResult:
    return LazyComputationResult(ready=ready, job_ids=job_ids if ready else [])


@time_machine.travel(datetime(2026, 3, 31, 12, tzinfo=UTC), tick=False)
class TestDimensionalReadSelection(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_compare", None, datetime(2026, 3, 1, 5, tzinfo=UTC)),
            (
                "compare_period_widens_start",
                datetime(2026, 2, 1, tzinfo=_NEW_YORK),
                datetime(2026, 2, 1, 5, tzinfo=UTC),
            ),
        ]
    )
    def test_opted_in_query_checks_the_utc_range_up_to_now(self, _name, compare_from, expected_start):
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=False),
            patch(f"{_READ}.dimensional_job_ids", return_value=_JOB_IDS) as mock_job_ids,
        ):
            assert ready_dimensional_job_ids(_runner(True, compare_from)) == _JOB_IDS

        _team, start, end = mock_job_ids.call_args.args
        assert (start, end) == (expected_start, datetime(2026, 3, 31, 12, tzinfo=UTC))
        assert start.tzinfo == UTC and end.tzinfo == UTC

    @parameterized.expand(
        [
            ("no_modifiers", None, False, _JOB_IDS),
            ("opted_out", False, False, _JOB_IDS),
            ("property_access_rules", True, True, _JOB_IDS),
            ("not_ready", True, False, None),
            ("lookup_fails", True, False, RuntimeError("postgres down")),
        ]
    )
    def test_query_falls_back(self, _name, opted_in, has_rules, job_ids):
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=has_rules),
            patch(f"{_READ}.dimensional_job_ids", side_effect=[job_ids]),
        ):
            assert ready_dimensional_job_ids(_runner(opted_in)) is None

    @parameterized.expand(
        [
            ("both_ready", True, True, _JOB_IDS),
            ("stats_gap", False, True, None),
            ("bounces_gap", True, False, None),
        ]
    )
    def test_dimensional_job_ids_needs_both_tables_ready_and_only_checks(
        self, _name, stats_ready, bounces_ready, expected
    ):
        with (
            patch(
                f"{_PRECOMPUTE}.ensure_web_stats_dimensional_precomputed", return_value=_result(stats_ready, _STATS_IDS)
            ) as mock_stats,
            patch(
                f"{_PRECOMPUTE}.ensure_web_bounces_dimensional_precomputed",
                return_value=_result(bounces_ready, _BOUNCES_IDS),
            ) as mock_bounces,
        ):
            assert (
                dimensional_job_ids(MagicMock(), datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC))
                == expected
            )

        for mock_ensure in (mock_stats, mock_bounces):
            if mock_ensure.called:
                assert mock_ensure.call_args.kwargs["run_inserts"] is False

    @parameterized.expand(
        [
            ("stats", WEB_STATS_DIMENSIONAL_READ_TABLE, _STATS_IDS),
            ("bounces", WEB_BOUNCES_DIMENSIONAL_READ_TABLE, _BOUNCES_IDS),
        ]
    )
    def test_builder_reads_dimensional_tables_filtered_to_their_job_ids(self, _name, table_name, job_ids):
        runner = _runner(True)
        runner.query_date_range.date_from.return_value = datetime(2026, 3, 1, tzinfo=UTC)
        builder = DimensionalStatsTableQueryBuilder(runner, _JOB_IDS)

        assert (builder.stats_table, builder.bounces_table) == (
            WEB_STATS_DIMENSIONAL_READ_TABLE,
            WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
        )
        job_id_filters = [
            expr
            for expr in builder._get_filters(table_name).exprs
            if isinstance(expr, ast.CompareOperation) and expr.op == ast.CompareOperationOp.In
        ]
        assert len(job_id_filters) == 1
        assert job_id_filters[0].left == ast.Field(chain=[table_name, "job_id"])
        assert job_id_filters[0].right == ast.Constant(value=[str(job_id) for job_id in job_ids])
