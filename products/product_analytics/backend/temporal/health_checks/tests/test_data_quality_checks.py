from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.product_analytics.backend.models.insight import Insight, InsightViewed
from products.product_analytics.backend.temporal.health_checks.duplicate_pageviews import DuplicatePageviewsCheck
from products.product_analytics.backend.temporal.health_checks.local_development_traffic import (
    LocalDevelopmentTrafficCheck,
)
from products.product_analytics.backend.temporal.health_checks.stopped_funnel_steps import StoppedFunnelStepsCheck

HOST_FILTER = {"key": "$host", "type": "event", "operator": "not_regex", "value": "localhost"}


class TestLocalDevelopmentTrafficCheck(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("mostly_local", 60, 80, [], "warning"),
            ("rarely_local", 60, 6000, [], "info"),
            ("local_hosts_filtered", 60, 80, [HOST_FILTER], None),
        ]
    )
    def test_flags_local_pageviews_the_internal_filter_misses(self, _name, local, other, filters, expected_severity):
        self.team.test_account_filters = filters
        self.team.save()
        for i, host in enumerate(["localhost:3000"] * local + ["example.com"] * other):
            _create_event(team=self.team, event="$pageview", distinct_id=f"person{i}", properties={"$host": host})
        flush_persons_and_events()

        issues = LocalDevelopmentTrafficCheck().detect([self.team.id])

        severity = issues[self.team.id][0].severity if self.team.id in issues else None
        self.assertEqual(severity, expected_severity)


class TestDuplicatePageviewsCheck(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [("sent_twice", timedelta(milliseconds=120), 1.0 / 2), ("viewed_again_later", timedelta(seconds=5), None)]
    )
    def test_flags_pageviews_sent_twice_within_a_second(self, _name, gap, expected_share):
        start = timezone.now().replace(microsecond=0) - timedelta(hours=1)
        for i in range(150):
            for timestamp in (start + timedelta(seconds=10 * i), start + timedelta(seconds=10 * i) + gap):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"person{i}",
                    timestamp=timestamp,
                    properties={"$current_url": "https://example.com/pricing"},
                )
        flush_persons_and_events()

        issues = DuplicatePageviewsCheck().detect([self.team.id])

        share = issues[self.team.id][0].payload["duplicate_share"] if self.team.id in issues else None
        self.assertEqual(share, expected_share)


class TestStoppedFunnelStepsCheck(ClickhouseTestMixin, BaseTest):
    def _funnel(self, name: str, steps: list[str], *, used_days_ago: int) -> Insight:
        insight = Insight.objects.create(
            team=self.team,
            name=name,
            query={
                "kind": "InsightVizNode",
                "source": {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": e} for e in steps]},
            },
        )
        InsightViewed.objects.create(
            team=self.team,
            user=self.user,
            insight=insight,
            last_viewed_at=timezone.now() - timedelta(days=used_days_ago),
        )
        return insight

    def _daily_events(self, event: str, days_ago: range) -> None:
        noon = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        for day in days_ago:
            _create_event(team=self.team, event=event, distinct_id="user", timestamp=noon - timedelta(days=day))
        EventDefinition.objects.create(
            team=self.team, project=self.project, name=event, last_seen_at=noon - timedelta(days=min(days_ago))
        )

    def test_flags_a_step_that_stopped_while_the_step_before_it_still_arrives(self):
        broken = self._funnel("Signup funnel", ["signup_started", "signup_completed"], used_days_ago=1)
        self._funnel("Signup funnel seen before the stop", ["signup_started", "signup_completed"], used_days_ago=12)
        self._funnel("Retired onboarding", ["onboarding_started", "onboarding_finished"], used_days_ago=1)
        dashboard_funnel = self._funnel(
            "Checkout funnel", ["checkout_started", "weekly_digest_opened"], used_days_ago=40
        )
        dashboard = Dashboard.objects.create(team=self.team, last_accessed_at=timezone.now())
        DashboardTile.objects.create(dashboard=dashboard, insight=dashboard_funnel)
        self._daily_events("signup_started", range(0, 41))
        self._daily_events("signup_completed", range(10, 41))
        self._daily_events("onboarding_started", range(10, 41))
        self._daily_events("onboarding_finished", range(10, 41))
        self._daily_events("checkout_started", range(0, 41))
        self._daily_events("weekly_digest_opened", range(10, 41, 7))
        flush_persons_and_events()

        issues = StoppedFunnelStepsCheck().detect([self.team.id])

        self.assertEqual(
            [result.payload for result in issues[self.team.id]],
            [
                {
                    "event": "signup_completed",
                    "previous_step": "signup_started",
                    "last_seen": (timezone.now() - timedelta(days=10)).date().isoformat(),
                    "funnel_count": 1,
                    "funnels": [{"short_id": broken.short_id, "name": "Signup funnel"}],
                }
            ],
        )
