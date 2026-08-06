from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import (
    DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE,
    TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL,
)

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import (
    build_touchpoints_precompute_query,
)


@override_settings(IN_UNIT_TESTING=True)
class TestMarketingTouchpointsPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self._clean()

    def tearDown(self):
        self._clean()
        super().tearDown()

    def _clean(self):
        sync_execute(TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL())
        PreaggregationJob.objects.all().delete()

    def _seed(self):
        for distinct_id in ("u1", "u2", "u3"):
            _create_person(distinct_ids=[distinct_id], team=self.team)

        # u1: two UTM-tagged pageviews → two touchpoints.
        for day, (campaign, source) in [(3, ("spring", "google")), (6, ("summer", "facebook"))]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="u1",
                timestamp=datetime(2025, 1, day, 10, tzinfo=UTC),
                properties={"utm_campaign": campaign, "utm_source": source, "utm_medium": "cpc"},
            )

        # u2: one UTM-tagged pageview + one pageview with no UTM (excluded).
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="u2",
            timestamp=datetime(2025, 1, 5, 10, tzinfo=UTC),
            properties={"utm_campaign": "winter", "utm_source": "bing"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="u2",
            timestamp=datetime(2025, 1, 7, 10, tzinfo=UTC),
            properties={},
        )

        # u3: a non-pageview event carrying UTM (excluded — only $pageview is a touchpoint).
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="u3",
            timestamp=datetime(2025, 1, 8, 10, tzinfo=UTC),
            properties={"utm_campaign": "x", "utm_source": "y"},
        )
        flush_persons_and_events()

    def _ensure(self):
        return ensure_precomputed(
            team=self.team,
            insert_query=build_touchpoints_precompute_query(),
            time_range_start=datetime(2025, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2025, 1, 31, tzinfo=UTC),
            ttl_seconds=3600,
            table=LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
        )

    def _count_touchpoints(self) -> int:
        rows = sync_execute(
            f"SELECT count() FROM {DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE()} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        return rows[0][0]

    def test_touchpoints_materialize_through_framework(self):
        self._seed()
        result = self._ensure()
        assert result.ready
        # Three UTM-tagged pageviews; the no-UTM pageview and the purchase are excluded.
        assert self._count_touchpoints() == 3

    def test_config_agnostic_query_reuses_one_job(self):
        self._seed()
        first = self._ensure()
        second = self._ensure()
        assert first.ready and second.ready
        # Identical (config-agnostic) query hash → the second call reuses the same job(s), no re-materialize.
        assert set(first.job_ids) == set(second.job_ids)
        assert self._count_touchpoints() == 3
