from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    InfinityValue,
    MarketingAnalyticsAggregatedQueryResponse,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQueryResponse,
    WebAnalyticsItemKind,
)

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner import (
    COSTS_EMPTY_RESULT_MAX_AGE_SECONDS,
    COSTS_EMPTY_RESULT_TTL_SECONDS,
    COSTS_PRECOMPUTE_MAX_WINDOW_DAYS,
    COSTS_PRECOMPUTE_TTL_SECONDS,
    costs_precompute_ttl_schedule,
    strip_infinity_sentinels,
)


def _item(change_pct: float | None) -> MarketingAnalyticsItem:
    return MarketingAnalyticsItem(
        key="Cost",
        kind=WebAnalyticsItemKind.CURRENCY,
        value=100.0,
        previous=0.0,
        changeFromPreviousPct=change_pct,
        hasComparison=True,
    )


@freeze_time("2026-06-15T12:00:00Z")
class TestCostsPrecomputeTtlSchedule(BaseTest):
    """The read path and the Dagster warmer both build their schedule here.

    Nothing else pins that the cost path actually opts into the empty-window cap, which is the
    gap that let an unsynced window stay cached as $0 in the first place — a refactor that dropped
    the opt-in would leave every test green.

    Frozen because the band cutoffs are resolved when the schedule is *built* (`parse_ttl_schedule`
    runs `relative_date_parse("0d")` eagerly) while the assertions pass a separately-sampled `now`.
    Midday UTC keeps the two on the same side of every boundary.
    """

    def test_opts_into_the_empty_result_cap(self):
        schedule = costs_precompute_ttl_schedule(self.team)

        assert schedule.empty_result_ttl_seconds == COSTS_EMPTY_RESULT_TTL_SECONDS
        assert schedule.empty_result_max_age_seconds == COSTS_EMPTY_RESULT_MAX_AGE_SECONDS

    def test_jobs_are_day_granular(self):
        # Emptiness is only observable per job, so a merged multi-day job would hide a sync gap
        # that sat next to productive days.
        assert costs_precompute_ttl_schedule(self.team).max_window_days == COSTS_PRECOMPUTE_MAX_WINDOW_DAYS == 1

    def test_keeps_the_band_ttls(self):
        schedule = costs_precompute_ttl_schedule(self.team)

        assert schedule.default_ttl_seconds == COSTS_PRECOMPUTE_TTL_SECONDS["default"]
        assert schedule.get_ttl(datetime.now(UTC)) == COSTS_PRECOMPUTE_TTL_SECONDS["0d"]

    def test_recent_empty_window_is_capped_but_old_one_is_not(self):
        schedule = costs_precompute_ttl_schedule(self.team)
        now = datetime.now(UTC)

        recent = schedule.empty_result_expires_at(now, now - timedelta(hours=1))
        assert recent is not None
        assert abs((recent - now).total_seconds() - COSTS_EMPTY_RESULT_TTL_SECONDS) < 1

        # Past the horizon, empty means empty — keep the band TTL instead of rescanning history.
        old_window_end = now - timedelta(seconds=COSTS_EMPTY_RESULT_MAX_AGE_SECONDS + 60)
        assert schedule.empty_result_expires_at(now, old_window_end) is None


class TestStripInfinitySentinels:
    @parameterized.expand(
        [
            (float(InfinityValue.NUMBER_999999), None),
            (float(InfinityValue.NUMBER__999999), None),
            (42.0, 42.0),
            (0.0, 0.0),
            (None, None),
        ]
    )
    def test_table_response_cells(self, change_pct: float | None, expected: float | None) -> None:
        response = MarketingAnalyticsTableQueryResponse(results=[[_item(change_pct), _item(7.0)]])
        strip_infinity_sentinels(response)
        assert response.results[0][0].changeFromPreviousPct == expected
        assert response.results[0][1].changeFromPreviousPct == 7.0

    def test_aggregated_response_dict_results(self) -> None:
        response = MarketingAnalyticsAggregatedQueryResponse(
            results={"cost": _item(float(InfinityValue.NUMBER_999999)), "clicks": _item(12.0)}
        )
        strip_infinity_sentinels(response)
        assert response.results["cost"].changeFromPreviousPct is None
        assert response.results["clicks"].changeFromPreviousPct == 12.0
