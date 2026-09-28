from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    InfinityValue,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsAggregatedQueryResponse,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    WebAnalyticsItemKind,
)

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner import (
    COSTS_EMPTY_RESULT_MAX_AGE_SECONDS,
    COSTS_EMPTY_RESULT_TTL_SECONDS,
    COSTS_PRECOMPUTE_MAX_WINDOW_DAYS,
    COSTS_PRECOMPUTE_TTL_SECONDS,
    costs_precompute_ttl_schedule,
    strip_infinity_sentinels,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def _item(change_pct: float | None) -> MarketingAnalyticsItem:
    return MarketingAnalyticsItem(
        key="Cost",
        kind=WebAnalyticsItemKind.CURRENCY,
        value=100.0,
        previous=0.0,
        changeFromPreviousPct=change_pct,
        hasComparison=True,
    )


@pytest.mark.ee
class TestMarketingQueryCachePermissions(BaseTest):
    @parameterized.expand(
        [
            ("table", MarketingAnalyticsTableQuery(properties=[])),
            ("aggregate", MarketingAnalyticsAggregatedQuery(properties=[])),
        ]
    )
    def test_marketing_queries_partition_cache_on_stored_warehouse_sources(
        self, _name: str, query: MarketingAnalyticsTableQuery | MarketingAnalyticsAggregatedQuery
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="campaign_costs",
            format="Parquet",
            url_pattern="https://bucket.s3/data/*",
            columns={},
        )
        key_granted = get_query_runner(query, self.team, user=self.user).get_cache_key()
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(table.id),
            organization_member=self.organization_membership,
            access_level="none",
        )
        key_denied = get_query_runner(query, self.team, user=self.user).get_cache_key()
        assert key_denied != key_granted


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
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
