from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.product_analytics.backend.models.insight import Insight, InsightViewed
from products.product_analytics.backend.temporal.health_checks.internal_traffic import InternalTrafficCheck
from products.product_analytics.backend.temporal.health_checks.stopped_insight_events import StoppedInsightEventsCheck


class TestInternalTrafficCheck(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("no_host_filter", [], {"internal_pageviews": 60, "pageviews": 160, "internal_share": 0.375}),
            (
                "host_excluded_by_internal_filter",
                [{"key": "$host", "type": "event", "operator": "not_regex", "value": "localhost"}],
                None,
            ),
        ]
    )
    def test_flags_local_pageviews_unless_the_internal_filter_excludes_them(self, _name, filters, expected_payload):
        self.team.test_account_filters = filters
        self.team.save()
        for i in range(60):
            _create_event(
                team=self.team, event="$pageview", distinct_id=f"dev{i}", properties={"$host": "localhost:3000"}
            )
        for i in range(100):
            _create_event(
                team=self.team, event="$pageview", distinct_id=f"user{i}", properties={"$host": "example.com"}
            )
        flush_persons_and_events()

        issues = InternalTrafficCheck().detect([self.team.id])

        payload = issues[self.team.id][0].payload if self.team.id in issues else None
        self.assertEqual(payload, expected_payload)


class TestStoppedInsightEventsCheck(ClickhouseTestMixin, BaseTest):
    def _insight(self, event: str, *, in_use: bool) -> Insight:
        insight = Insight.objects.create(
            team=self.team,
            name=f"{event} trend",
            query={
                "kind": "InsightVizNode",
                "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": event}]},
            },
        )
        if in_use:
            InsightViewed.objects.create(team=self.team, user=self.user, insight=insight, last_viewed_at=timezone.now())
        return insight

    def _events(self, event: str, days_ago: range) -> None:
        noon = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        for day in days_ago:
            _create_event(team=self.team, event=event, distinct_id="user", timestamp=noon - timedelta(days=day))
        EventDefinition.objects.create(
            team=self.team, project=self.project, name=event, last_seen_at=noon - timedelta(days=min(days_ago))
        )

    def test_flags_a_daily_event_that_stopped_only_when_an_insight_in_use_reads_it(self):
        stopped = self._insight("signed_up", in_use=True)
        self._insight("legacy_signup", in_use=False)
        self._insight("weekly_report", in_use=True)
        self._insight("purchase", in_use=True)
        self._events("signed_up", range(10, 41))
        self._events("legacy_signup", range(10, 41))
        self._events("weekly_report", range(10, 41, 7))
        self._events("purchase", range(0, 41))
        flush_persons_and_events()

        issues = StoppedInsightEventsCheck().detect([self.team.id])

        last_seen = (timezone.now() - timedelta(days=10)).date().isoformat()
        self.assertEqual(
            [result.payload for result in issues[self.team.id]],
            [
                {
                    "event": "signed_up",
                    "last_seen": last_seen,
                    "insight_count": 1,
                    "insights": [{"short_id": stopped.short_id, "name": "signed_up trend"}],
                }
            ],
        )
