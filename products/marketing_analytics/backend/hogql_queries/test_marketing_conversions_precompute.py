from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from posthog.schema import BaseMathType, ConversionGoalFilter1

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.marketing_conversions_sql import (
    DISTRIBUTED_MARKETING_CONVERSIONS_TABLE,
    TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL,
)

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import ConversionGoalProcessor
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig


@override_settings(IN_UNIT_TESTING=True)
class TestMarketingConversionsPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self._clean()

    def tearDown(self):
        self._clean()
        super().tearDown()

    def _clean(self):
        sync_execute(TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL())
        PreaggregationJob.objects.all().delete()

    def _seed(self):
        for distinct_id in ("u1", "u2", "u3"):
            _create_person(distinct_ids=[distinct_id], team=self.team)

        # u1: two purchases → two conversions.
        for day in (3, 6):
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id="u1",
                timestamp=datetime(2025, 1, day, 10, tzinfo=UTC),
                properties={"utm_campaign": "spring", "utm_source": "google"},
            )

        # u2: one purchase + one pageview (excluded — only the goal event is a conversion).
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="u2",
            timestamp=datetime(2025, 1, 5, 10, tzinfo=UTC),
            properties={"utm_campaign": "winter", "utm_source": "bing"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="u2",
            timestamp=datetime(2025, 1, 7, 10, tzinfo=UTC),
            properties={"utm_campaign": "x", "utm_source": "y"},
        )

        # u3: a different event (excluded — not the goal event).
        _create_event(
            team=self.team,
            event="signup",
            distinct_id="u3",
            timestamp=datetime(2025, 1, 8, 10, tzinfo=UTC),
            properties={},
        )
        flush_persons_and_events()

    def _make_processor(self, event: str = "purchase") -> ConversionGoalProcessor:
        goal = ConversionGoalFilter1(
            kind="EventsNode",
            event=event,
            conversion_goal_id=f"goal_{event}",
            conversion_goal_name=event,
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            properties=[],
        )
        config = MarketingAnalyticsConfig()
        config.attribution_window_days = 30
        return ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=config)

    def _ensure(self, processor: ConversionGoalProcessor):
        return ensure_precomputed(
            team=self.team,
            insert_query=processor.build_conversions_precompute_query(),
            time_range_start=datetime(2025, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2025, 1, 31, tzinfo=UTC),
            ttl_seconds=3600,
            table=LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED,
        )

    def _count_conversions(self) -> int:
        rows = sync_execute(
            f"SELECT count() FROM {DISTRIBUTED_MARKETING_CONVERSIONS_TABLE()} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        return rows[0][0]

    def test_conversions_materialize_through_framework(self):
        self._seed()
        result = self._ensure(self._make_processor())
        assert result.ready
        # Three purchases; the pageview and the signup are excluded (not the goal event).
        assert self._count_conversions() == 3

    def test_same_goal_reuses_one_job(self):
        self._seed()
        first = self._ensure(self._make_processor())
        second = self._ensure(self._make_processor())
        assert first.ready and second.ready
        # Identical goal → identical query hash → the second call reuses the same job(s).
        assert set(first.job_ids) == set(second.job_ids)
        assert self._count_conversions() == 3

    def test_different_goal_uses_different_job(self):
        self._seed()
        purchase = self._ensure(self._make_processor(event="purchase"))
        signup = self._ensure(self._make_processor(event="signup"))
        assert purchase.ready and signup.ready
        # Different conversion event → different query hash → a distinct job per goal.
        assert set(purchase.job_ids).isdisjoint(set(signup.job_ids))
