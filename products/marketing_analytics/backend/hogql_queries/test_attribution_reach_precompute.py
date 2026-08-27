"""The reach denominator served from the pre-aggregated table instead of a live pageview scan.

Reach feeds `conversionRate = conversions / visitors` for all five models at once, so a wrong
denominator here does not crash, it produces five plausible-looking but wrong rates. These tests are
therefore mostly about the two sides *agreeing*: the pre-aggregated path has to render a dimension to
the same string the credit side does, or the FULL OUTER JOIN in `_build_rows_select` splits it into a
visitors-only row and a credit-only row.
"""

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    CustomChannelRule,
    DateRange,
    HogQLQueryModifiers,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionQuery,
)

from posthog.hogql.printer import prepare_and_print_ast

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.backend.hogql_queries.attribution_reach_precompute import REACH_PRECOMPUTE_TABLE
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)

GOAL_ID = "goal-1"
CONVERSION_EVENT = "purchase"

ENSURE_PATH = (
    "products.marketing_analytics.backend.hogql_queries.attribution_reach_precompute.marketing_ensure_precomputed"
)


class TestAttributionReachPrecompute(ClickhouseTestMixin, BaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        config = self.team.marketing_analytics_config
        config.attribution_window_days = 30
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=CONVERSION_EVENT,
                name="Purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchases",
                schema_map={},
                math=BaseMathType.TOTAL,
            ).model_dump()
        ]
        config.save()
        # The flag cache lives on the team instance, so clear it between cases (see
        # `MarketingAnalyticsConfig._precompute_flags`).
        self._set_reach_flag(True)

    def _set_reach_flag(self, enabled: bool) -> None:
        for attr in ("_ma_precompute_flags", "_ma_multi_touch_flag"):
            if hasattr(self.team, attr):
                delattr(self.team, attr)
        self.team._ma_precompute_flags = {  # type: ignore[attr-defined]
            "conversion": False,
            "costs": False,
            "reach": enabled,
        }

    def _sql(self, *, breakdown=MarketingAnalyticsAttributionBreakdown.CHANNEL, modifiers=None, **query_kwargs) -> str:
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=GOAL_ID,
            breakdownBy=breakdown,
            properties=[],
            **query_kwargs,
        )
        runner = MarketingAnalyticsAttributionQueryRunner(
            query=query, team=self.team, user=self.user, modifiers=modifiers
        )
        context = runner._shared_hogql_context
        context.enable_select_queries = True
        return prepare_and_print_ast(runner.to_query(), context=context, dialect="clickhouse")[0]

    def _ready(self) -> LazyComputationResult:
        return LazyComputationResult(ready=True, job_ids=[self.team.uuid])

    def test_reach_reads_the_preaggregated_table_when_the_job_is_ready(self):
        with patch(ENSURE_PATH, return_value=self._ready()):
            sql = self._sql()

        assert REACH_PRECOMPUTE_TABLE in sql
        # The credit side still scans events; only the denominator moved.
        assert "person_arrays" in sql

    def test_falls_back_to_the_live_scan_when_the_job_is_not_ready(self):
        with patch(ENSURE_PATH, return_value=LazyComputationResult(ready=False, job_ids=[])):
            sql = self._sql()

        assert REACH_PRECOMPUTE_TABLE not in sql

    def test_falls_back_when_the_ensure_call_raises(self):
        # A precompute that blows up must degrade to the live path, not surface an error to a user who
        # never opted into a different data source.
        with patch(ENSURE_PATH, side_effect=RuntimeError("clickhouse is having a day")):
            sql = self._sql()

        assert REACH_PRECOMPUTE_TABLE not in sql

    # The pre-aggregated channel type cannot apply custom rules, because they can key on the full
    # URL, which no pre-aggregated table stores. The credit side reads `sessions.$channel_type`,
    # which does apply them, so serving reach from the precompute would disagree with the numerator.
    def test_falls_back_for_a_team_with_custom_channel_rules(self):
        modifiers = HogQLQueryModifiers(
            customChannelTypeRules=[
                CustomChannelRule(
                    id="rule-1",
                    items=[],
                    combiner="OR",
                    channel_type="My Custom Channel",
                )
            ]
        )
        with patch(ENSURE_PATH, return_value=self._ready()):
            sql = self._sql(modifiers=modifiers)

        assert REACH_PRECOMPUTE_TABLE not in sql

    @parameterized.expand([("half_hour", "Asia/Kolkata"), ("three_quarter_hour", "Asia/Kathmandu")])
    def test_falls_back_for_a_non_integer_offset_timezone(self, _name: str, tz: str):
        # An integer-offset team's midnight lands on a bucket edge, so the comparison is exact. A
        # half-hour-offset team's lands mid-bucket, moving up to an hour of sessions across each edge.
        self.team.timezone = tz
        self.team.save()
        with patch(ENSURE_PATH, return_value=self._ready()) as ensure:
            sql = self._sql()

        assert REACH_PRECOMPUTE_TABLE not in sql
        # Rejected before any precompute work is done, not after paying for it.
        ensure.assert_not_called()

    @parameterized.expand([("utc", "UTC"), ("negative_offset", "US/Pacific"), ("positive_offset", "Asia/Tokyo")])
    def test_integer_offset_timezones_still_use_the_precompute(self, _name: str, tz: str):
        # The counterpart to the test above: the gate must reject only what it has to. ClickHouse
        # compares the boundary and `period_bucket` as absolute instants, so an integer offset lines up.
        self.team.timezone = tz
        self.team.save()
        with patch(ENSURE_PATH, return_value=self._ready()):
            sql = self._sql()

        assert REACH_PRECOMPUTE_TABLE in sql

    def test_flag_off_never_touches_the_precompute(self):
        self._set_reach_flag(False)
        with patch(ENSURE_PATH, return_value=self._ready()) as ensure:
            sql = self._sql()

        assert REACH_PRECOMPUTE_TABLE not in sql
        ensure.assert_not_called()

    @parameterized.expand(
        [
            (MarketingAnalyticsAttributionBreakdown.SOURCE, "utm_source"),
            (MarketingAnalyticsAttributionBreakdown.CAMPAIGN, "utm_campaign"),
            (MarketingAnalyticsAttributionBreakdown.MEDIUM, "utm_medium"),
            (MarketingAnalyticsAttributionBreakdown.CONTENT, "utm_content"),
            (MarketingAnalyticsAttributionBreakdown.TERM, "utm_term"),
            (MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN, "referring_domain"),
            (MarketingAnalyticsAttributionBreakdown.LANDING_PAGE, "entry_pathname"),
        ]
    )
    def test_every_breakdown_maps_to_its_column(self, breakdown, expected_column: str):
        with patch(ENSURE_PATH, return_value=self._ready()):
            sql = self._sql(breakdown=breakdown)

        assert REACH_PRECOMPUTE_TABLE in sql
        assert f"{REACH_PRECOMPUTE_TABLE}.{expected_column}" in sql

    def test_visitors_merge_the_uniq_state_rather_than_counting_rows(self):
        # `host` and `device_type` are event-level, so one session can occupy several rows. Counting
        # rows would inflate a multi-host session; merging the state collapses it back to one person.
        with patch(ENSURE_PATH, return_value=self._ready()):
            sql = self._sql()

        assert "uniqMerge" in sql

    def test_window_extends_back_by_the_attribution_window(self):
        # Bounding visitors to the display range while conversions can be credited to an earlier
        # touch puts a person in the numerator but not the denominator, giving rates above 100%.
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return self._ready()

        with patch(ENSURE_PATH, side_effect=_capture):
            self._sql()

        # 30-day attribution window on a range starting 2023-01-01.
        assert captured["time_range_start"].date().isoformat() == "2022-12-02"
