import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import (
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
    EventPropertyFilter,
    FilterLogicalOperator,
    HogQLQueryModifiers,
    MaterializationMode,
    PersonsOnEventsMode,
    PropertyOperator,
    SessionPropertyFilter,
    SessionTableVersion,
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
    WEB_ANALYTICS_DIMENSIONAL_READS_DISABLED_FLAG,
    WEB_ANALYTICS_QUERY_MODIFIERS_FLAG,
    DimensionalStatsTableQueryBuilder,
    ready_dimensional_job_ids,
)

_READ = "products.web_analytics.backend.hogql_queries.web_dimensional_read"
_PRECOMPUTE = "products.web_analytics.backend.hogql_queries.web_dimensional_precompute"
_STATS_IDS = [uuid.uuid4()]
_BOUNCES_IDS = [uuid.uuid4()]
_JOB_IDS = DimensionalJobIds(stats=_STATS_IDS, bounces=_BOUNCES_IDS)
_BOTH_TABLES = (WEB_STATS_DIMENSIONAL_READ_TABLE, WEB_BOUNCES_DIMENSIONAL_READ_TABLE)
_NEW_YORK = ZoneInfo("America/New_York")
_SESSIONS_V3_FLOOR = datetime(2026, 2, 15, tzinfo=UTC)
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


def _event_filter(key: str, value: str = "x") -> EventPropertyFilter:
    return EventPropertyFilter(key=key, value=value, operator=PropertyOperator.EXACT)


def _session_filter(key: str, value: str = "x") -> SessionPropertyFilter:
    return SessionPropertyFilter(key=key, value=value, operator=PropertyOperator.EXACT)


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
    kind: str = "WebStatsTableQuery",
    modifiers: HogQLQueryModifiers | None = None,
    team_modifiers: dict | None = None,
) -> MagicMock:
    runner = MagicMock()
    runner.team.pk = 1
    runner.team.modifiers = team_modifiers
    runner.query.kind = kind
    runner.query.webQueryModifiers = (
        None if opted_in is None else WebAnalyticsQueryModifiers(useDimensionalTables=opted_in)
    )
    runner.query.properties = properties or []
    runner.query.breakdownBy = breakdown_by
    runner.modifiers = modifiers or HogQLQueryModifiers(customChannelTypeRules=custom_channel_rules)
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


def _result(
    ready: bool, job_ids: list[uuid.UUID], stale: bool = False, computed_at: datetime | None = None
) -> LazyComputationResult:
    return LazyComputationResult(
        ready=ready, job_ids=job_ids if ready else [], stale=stale, computed_at=computed_at if ready else None
    )


@time_machine.travel(datetime(2026, 3, 31, 12, tzinfo=UTC), tick=False)
class TestDimensionalReadSelection(SimpleTestCase):
    def setUp(self) -> None:
        retention_patcher = patch(f"{_READ}.events_retention_months_for_team", return_value=None)
        self.retention_months = retention_patcher.start()
        self.addCleanup(retention_patcher.stop)
        insert_modifiers_patcher = patch(f"{_READ}.dimensional_insert_modifiers", return_value=HogQLQueryModifiers())
        insert_modifiers_patcher.start()
        self.addCleanup(insert_modifiers_patcher.stop)
        self.flags = {WEB_ANALYTICS_QUERY_MODIFIERS_FLAG: True, WEB_ANALYTICS_DIMENSIONAL_READS_DISABLED_FLAG: False}
        flag_patcher = patch(
            f"{_READ}.feature_enabled_or_false", side_effect=lambda key, *args, **kwargs: self.flags[key]
        )
        self.flag_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

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
            assert ready_dimensional_job_ids(_runner(True, compare_from, tz=tz), _BOTH_TABLES) == _JOB_IDS

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
            ("not_ready", _runner(True), False, None),
            ("lookup_fails", _runner(True), False, RuntimeError("postgres down")),
            (
                "overview_pathname_filter",
                _runner(True, kind="WebOverviewQuery", properties=[_event_filter("$pathname", "/pricing")]),
                False,
                _JOB_IDS,
            ),
            (
                "event_referring_domain_filter",
                _runner(True, properties=[_event_filter("$referring_domain", "example.com")]),
                False,
                _JOB_IDS,
            ),
            ("entry_gclid_value_filter", _runner(True, properties=[_session_filter("$entry_gclid")]), False, _JOB_IDS),
            (
                "entry_fbclid_value_filter",
                _runner(True, properties=[_session_filter("$entry_fbclid")]),
                False,
                _JOB_IDS,
            ),
            ("browser_version_filter", _runner(True, properties=[_event_filter("$browser_version")]), False, _JOB_IDS),
            ("os_version_filter", _runner(True, properties=[_event_filter("$os_version")]), False, _JOB_IDS),
            ("country_name_filter", _runner(True, properties=[_event_filter("$geoip_country_name")]), False, _JOB_IDS),
            ("time_zone_filter", _runner(True, properties=[_event_filter("$geoip_time_zone")]), False, _JOB_IDS),
            (
                "persons_on_events_mode_differs_from_the_build",
                _runner(True, modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)),
                False,
                _JOB_IDS,
            ),
            (
                "materialization_mode_differs_from_the_build",
                _runner(
                    True,
                    modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING),
                ),
                False,
                _JOB_IDS,
            ),
        ]
    )
    def test_query_falls_back(self, _name, runner, has_rules, job_ids):
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=has_rules),
            patch(f"{_READ}.dimensional_job_ids", side_effect=[job_ids]),
        ):
            assert ready_dimensional_job_ids(runner, _BOTH_TABLES) is None

    @parameterized.expand(
        [
            ("team_on_and_request_unset", None, True, True, False, True),
            ("team_off_and_request_unset", None, False, True, False, False),
            ("team_on_and_request_opts_out", False, True, True, False, False),
            ("team_off_and_request_opts_in_with_the_modifiers_flag", True, False, True, False, True),
            ("team_off_and_request_opts_in_without_the_modifiers_flag", True, False, False, False, False),
            ("team_on_and_request_opts_in_without_the_modifiers_flag", True, True, False, False, True),
            ("team_on_and_reads_disabled", None, True, True, True, False),
            ("request_opts_in_and_reads_disabled", True, False, True, True, False),
            ("team_off_and_the_request_supplies_the_team_modifier", None, False, True, False, False, True),
        ]
    )
    def test_opt_in_follows_the_request_then_the_team_modifier(
        self, _name, requested, team_modifier, modifiers_flag, reads_disabled, serves, request_modifier=None
    ):
        self.flags[WEB_ANALYTICS_QUERY_MODIFIERS_FLAG] = modifiers_flag
        self.flags[WEB_ANALYTICS_DIMENSIONAL_READS_DISABLED_FLAG] = reads_disabled
        runner = _runner(
            requested,
            modifiers=HogQLQueryModifiers(useWebAnalyticsDimensionalTables=request_modifier),
            team_modifiers={"useWebAnalyticsDimensionalTables": team_modifier},
        )
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=False),
            patch(f"{_READ}.dimensional_job_ids", return_value=_JOB_IDS) as mock_job_ids,
        ):
            assert ready_dimensional_job_ids(runner, _BOTH_TABLES) == (_JOB_IDS if serves else None)

        assert mock_job_ids.called == serves

    @parameterized.expand(
        [
            ("retention_not_enforced", _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK)), None, True),
            ("both_periods_inside_retention", _runner(True), 1, True),
            (
                "stats_table_pathname_filter",
                _runner(True, properties=[_event_filter("$pathname", "/pricing")]),
                None,
                True,
            ),
            (
                "compare_period_crosses_retention",
                _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK)),
                1,
                False,
            ),
            (
                "custom_channel_rules_differ_from_the_build",
                _runner(True, custom_channel_rules=_CUSTOM_CHANNEL_RULES),
                None,
                False,
            ),
            ("sessions_v3_after_the_floor", _runner(True), None, True, SessionTableVersion.V3),
            (
                "sessions_v3_compare_period_before_the_floor",
                _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK)),
                None,
                False,
                SessionTableVersion.V3,
            ),
            ("sessions_v3_region_without_a_backfill", _runner(True), None, False, SessionTableVersion.V3, "EU"),
            (
                "sessions_v2_before_the_v3_floor",
                _runner(True, compare_from=datetime(2026, 2, 1, tzinfo=_NEW_YORK)),
                None,
                True,
                SessionTableVersion.V2,
            ),
        ]
    )
    def test_query_serves_only_inside_retention_sessions_coverage_and_channel_rules(
        self,
        _name,
        runner,
        retention_months,
        serves,
        session_table_version=SessionTableVersion.AUTO,
        region="US",
    ):
        self.retention_months.return_value = retention_months
        build_modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        runner.modifiers.sessionTableVersion = session_table_version
        with (
            patch(f"{_READ}.team_has_property_access_rules", return_value=False),
            patch(f"{_READ}.dimensional_job_ids", return_value=_JOB_IDS),
            patch(f"{_READ}.dimensional_insert_modifiers", return_value=build_modifiers),
            patch(f"{_PRECOMPUTE}.is_cloud", return_value=True),
            patch.dict(f"{_PRECOMPUTE}.SESSIONS_V3_COVERAGE_START_BY_REGION", {"US": _SESSIONS_V3_FLOOR}, clear=True),
            override_settings(CLOUD_DEPLOYMENT=region),
        ):
            assert ready_dimensional_job_ids(runner, _BOTH_TABLES) == (_JOB_IDS if serves else None)

    @parameterized.expand(
        [
            ("both_ready", _BOTH_TABLES, _result(True, _STATS_IDS), _result(True, _BOUNCES_IDS), _JOB_IDS),
            ("stats_gap", _BOTH_TABLES, _result(False, _STATS_IDS), _result(True, _BOUNCES_IDS), None),
            ("bounces_gap", _BOTH_TABLES, _result(True, _STATS_IDS), _result(False, _BOUNCES_IDS), None),
            (
                "bounces_only_ignores_a_stats_gap",
                (WEB_BOUNCES_DIMENSIONAL_READ_TABLE,),
                _result(False, _STATS_IDS),
                _result(True, _BOUNCES_IDS),
                DimensionalJobIds(stats=None, bounces=_BOUNCES_IDS),
            ),
            (
                "stale_job_and_oldest_computed_at",
                _BOTH_TABLES,
                _result(True, _STATS_IDS, computed_at=datetime(2026, 3, 2, 10, tzinfo=UTC)),
                _result(True, _BOUNCES_IDS, stale=True, computed_at=datetime(2026, 3, 2, 9, tzinfo=UTC)),
                DimensionalJobIds(
                    stats=_STATS_IDS,
                    bounces=_BOUNCES_IDS,
                    stale=True,
                    computed_at=datetime(2026, 3, 2, 9, tzinfo=UTC),
                ),
            ),
        ]
    )
    def test_dimensional_job_ids_checks_only_the_requested_tables(
        self, _name, tables, stats_result, bounces_result, expected
    ):
        modifiers = HogQLQueryModifiers()
        with (
            patch(f"{_PRECOMPUTE}.ensure_web_stats_dimensional_precomputed", return_value=stats_result) as mock_stats,
            patch(
                f"{_PRECOMPUTE}.ensure_web_bounces_dimensional_precomputed", return_value=bounces_result
            ) as mock_bounces,
        ):
            assert (
                dimensional_job_ids(
                    MagicMock(),
                    datetime(2026, 3, 1, tzinfo=UTC),
                    datetime(2026, 3, 2, tzinfo=UTC),
                    tables=tables,
                    modifiers=modifiers,
                )
                == expected
            )

        assert mock_stats.called is (WEB_STATS_DIMENSIONAL_READ_TABLE in tables)
        for mock_ensure in (mock_stats, mock_bounces):
            if mock_ensure.called:
                assert mock_ensure.call_args.kwargs["run_inserts"] is False
                assert mock_ensure.call_args.kwargs["modifiers"] is modifiers

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
