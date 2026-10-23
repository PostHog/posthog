import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
    FilterLogicalOperator,
    PropertyOperator,
    SessionPropertyFilter,
    WebAnalyticsQueryModifiers,
    WebStatsBreakdown,
)

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
_TEST_ACCOUNT_FILTERS = [{"key": "email", "value": "@example.com", "operator": "not_icontains", "type": "person"}]
_CUSTOM_CHANNEL_RULES = [
    CustomChannelRule(
        id="docs",
        channel_type="Docs",
        combiner=FilterLogicalOperator.AND_,
        items=[
            CustomChannelCondition(
                id="url",
                key=CustomChannelField.URL,
                op=CustomChannelOperator.ICONTAINS,
                value="/docs",
            )
        ],
    )
]
_CHANNEL_FILTER = SessionPropertyFilter(key="$channel_type", value="Docs", operator=PropertyOperator.EXACT)


def _runner(
    opted_in: bool | None,
    compare_from: datetime | None = None,
    tz: ZoneInfo = _NEW_YORK,
    test_account_filters: list | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    compare_to: datetime | None = None,
    custom_channel_rules: list[CustomChannelRule] | None = None,
    breakdown_by: WebStatsBreakdown = WebStatsBreakdown.PAGE,
    properties: list | None = None,
) -> MagicMock:
    runner = MagicMock()
    runner.team.pk = 1
    runner.query.webQueryModifiers = (
        None if opted_in is None else WebAnalyticsQueryModifiers(useDimensionalTables=opted_in)
    )
    runner.query.properties = properties or []
    runner.query.breakdownBy = breakdown_by
    runner.modifiers.customChannelTypeRules = custom_channel_rules
    runner._test_account_filters = test_account_filters or []
    # A project-local range: the current day in New York ends after the UTC now below.
    runner.query_date_range.date_from.return_value = date_from or datetime(2026, 3, 1, tzinfo=tz)
    runner.query_date_range.date_to.return_value = date_to or datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=tz)
    if compare_from is None:
        runner.query_compare_to_date_range = None
    else:
        runner.query_compare_to_date_range.date_from.return_value = compare_from
        runner.query_compare_to_date_range.date_to.return_value = compare_to or (
            datetime(2026, 3, 1, tzinfo=compare_from.tzinfo) - timedelta(microseconds=1)
        )
    return runner


def _result(ready: bool, job_ids: list[uuid.UUID]) -> LazyComputationResult:
    return LazyComputationResult(ready=ready, job_ids=job_ids if ready else [])


@time_machine.travel(datetime(2026, 3, 31, 12, tzinfo=UTC), tick=False)
class TestDimensionalReadSelection(SimpleTestCase):
    def setUp(self) -> None:
        retention_patcher = patch(f"{_READ}.events_retention_months_for_team", return_value=None)
        self.retention_months = retention_patcher.start()
        self.addCleanup(retention_patcher.stop)

    @parameterized.expand(
        [
            ("no_compare", None, _NEW_YORK, datetime(2026, 3, 1, 5, tzinfo=UTC)),
            (
                "compare_period_widens_start",
                datetime(2026, 2, 1, tzinfo=_NEW_YORK),
                _NEW_YORK,
                datetime(2026, 2, 1, 5, tzinfo=UTC),
            ),
            ("whole_hour_east_of_utc", None, ZoneInfo("Asia/Tokyo"), datetime(2026, 2, 28, 15, tzinfo=UTC)),
        ]
    )
    def test_opted_in_query_checks_the_utc_range_up_to_now(self, _name, compare_from, tz, expected_start):
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=False),
            patch(f"{_READ}.dimensional_job_ids", return_value=_JOB_IDS) as mock_job_ids,
        ):
            assert ready_dimensional_job_ids(_runner(True, compare_from, tz=tz)) == _JOB_IDS

        _team, start, end = mock_job_ids.call_args.args
        assert (start, end) == (expected_start, datetime(2026, 3, 31, 12, tzinfo=UTC))
        assert start.tzinfo == UTC and end.tzinfo == UTC

    @parameterized.expand(
        [
            ("no_modifiers", _runner(None), False, _JOB_IDS),
            ("opted_out", _runner(False), False, _JOB_IDS),
            ("property_access_rules", _runner(True), True, _JOB_IDS),
            ("test_account_filters", _runner(True, test_account_filters=_TEST_ACCOUNT_FILTERS), False, _JOB_IDS),
            ("half_hour_timezone", _runner(True, tz=ZoneInfo("Asia/Kolkata")), False, _JOB_IDS),
            (
                "half_hour_timezone_in_compare_period_only",
                _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=ZoneInfo("Asia/Kolkata"))),
                False,
                _JOB_IDS,
            ),
            (
                "start_inside_an_hour",
                _runner(
                    True,
                    date_from=datetime(2026, 3, 1, 10, 30, tzinfo=UTC),
                    date_to=datetime(2026, 3, 1, 11, 59, 59, 999999, tzinfo=UTC),
                ),
                False,
                _JOB_IDS,
            ),
            (
                "past_end_inside_an_hour",
                _runner(
                    True,
                    date_from=datetime(2026, 3, 1, 10, tzinfo=UTC),
                    date_to=datetime(2026, 3, 1, 11, 30, tzinfo=UTC),
                ),
                False,
                _JOB_IDS,
            ),
            (
                "past_end_on_an_hour_boundary",
                _runner(
                    True,
                    date_from=datetime(2026, 3, 1, 10, tzinfo=UTC),
                    date_to=datetime(2026, 3, 1, 11, tzinfo=UTC),
                ),
                False,
                _JOB_IDS,
            ),
            (
                "compare_end_inside_an_hour",
                _runner(
                    True,
                    compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK),
                    compare_to=datetime(2026, 2, 28, 23, 59, 59, tzinfo=_NEW_YORK),
                ),
                False,
                _JOB_IDS,
            ),
            (
                "custom_channel_rules_with_channel_breakdown",
                _runner(
                    True,
                    custom_channel_rules=_CUSTOM_CHANNEL_RULES,
                    breakdown_by=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                ),
                False,
                _JOB_IDS,
            ),
            (
                "custom_channel_rules_with_channel_filter",
                _runner(True, custom_channel_rules=_CUSTOM_CHANNEL_RULES, properties=[_CHANNEL_FILTER]),
                False,
                _JOB_IDS,
            ),
            ("not_ready", _runner(True), False, None),
            ("lookup_fails", _runner(True), False, RuntimeError("postgres down")),
        ]
    )
    def test_query_falls_back(self, _name, runner, has_rules, job_ids):
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=has_rules),
            patch(f"{_READ}.dimensional_job_ids", side_effect=[job_ids]),
        ):
            assert ready_dimensional_job_ids(runner) is None

    @parameterized.expand(
        [
            ("retention_not_enforced", _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK)), None, True),
            ("both_periods_inside_retention", _runner(True), 1, True),
            (
                "compare_period_crosses_retention",
                _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK)),
                1,
                False,
            ),
            (
                "custom_channel_rules_without_channel_dependency",
                _runner(True, custom_channel_rules=_CUSTOM_CHANNEL_RULES),
                None,
                True,
            ),
        ]
    )
    def test_query_serves_only_inside_retention_and_channel_rules(self, _name, runner, retention_months, serves):
        self.retention_months.return_value = retention_months
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=False),
            patch(f"{_READ}.dimensional_job_ids", return_value=_JOB_IDS),
        ):
            assert ready_dimensional_job_ids(runner) == (_JOB_IDS if serves else None)

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
