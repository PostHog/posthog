import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema_enums import AlertState

from products.alerts.backend.models import AlertConfiguration
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_caching_state import InsightCachingState
from products.pulse.backend.sources.resource_health import STUCK_REFRESH_ATTEMPTS, ResourceHealthSource

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


class TestResourceHealthGather(BaseTest):
    def _insight(self, name: str = "Signup funnel") -> Insight:
        return Insight.objects.create(team=self.team, name=name, query=_TRENDS_QUERY)

    def _alert(self, **kwargs: Any) -> AlertConfiguration:
        defaults: dict[str, Any] = {
            "team": self.team,
            "insight": self._insight(),
            "name": "Signup alert",
            "state": AlertState.ERRORED,
            "enabled": True,
        }
        defaults.update(kwargs)
        return AlertConfiguration.objects.create(**defaults)

    def _subscription(self, title: str = "Weekly report") -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            title=title,
            target_type="email",
            target_value="team@posthog.com",
            frequency="weekly",
            start_date=timezone.now() - timedelta(days=30),
        )

    def _delivery(
        self, subscription: Subscription, status: str = SubscriptionDelivery.Status.FAILED, days_ago: float = 1
    ) -> SubscriptionDelivery:
        delivery = SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            temporal_workflow_id="wf",
            idempotency_key=str(uuid.uuid4()),
            trigger_type="scheduled",
            target_type="email",
            target_value="team@posthog.com",
            status=status,
        )
        # created_at is auto_now_add — move it explicitly to place the delivery in/out of period
        SubscriptionDelivery.objects.filter(id=delivery.id).update(created_at=timezone.now() - timedelta(days=days_ago))
        return delivery

    def _caching_state(
        self, insight: Insight, refresh_attempt: int, dashboard_tile: DashboardTile | None = None
    ) -> InsightCachingState:
        # Insight/tile creation auto-creates a caching state via signals, so update-or-create
        state, _ = InsightCachingState.objects.update_or_create(
            team=self.team,
            insight=insight,
            dashboard_tile=dashboard_tile,
            defaults={"refresh_attempt": refresh_attempt, "cache_key": f"cache_{uuid.uuid4()}"},
        )
        return state

    def test_healthy_team_yields_no_items(self) -> None:
        self._alert(state=AlertState.NOT_FIRING)
        self._delivery(self._subscription(), status=SubscriptionDelivery.Status.COMPLETED)
        self._caching_state(self._insight(), refresh_attempt=0)

        assert ResourceHealthSource().gather(self.team, None, period_days=7) == []

    def test_errored_alert_yields_health_item(self) -> None:
        alert = self._alert()

        items = ResourceHealthSource().gather(self.team, None, period_days=7)

        assert len(items) == 1
        item = items[0]
        assert item.source == "resource_health"
        assert item.kind == "health"
        assert "Signup alert" in item.title
        assert item.evidence == [{"type": "alert", "ref": str(alert.id), "label": "Signup alert"}]
        assert item.fingerprint_hint == f"health:alert:{alert.id}"

    @parameterized.expand(
        [
            ("disabled", {"enabled": False}),
            ("firing_not_errored", {"state": AlertState.FIRING}),
            ("snoozed", {"state": AlertState.SNOOZED}),
        ]
    )
    def test_non_errored_alerts_ignored(self, _name: str, overrides: dict[str, Any]) -> None:
        self._alert(**overrides)

        assert ResourceHealthSource().gather(self.team, None, period_days=7) == []

    def test_failed_deliveries_grouped_per_subscription(self) -> None:
        subscription = self._subscription()
        self._delivery(subscription, days_ago=1)
        self._delivery(subscription, days_ago=2)
        self._delivery(subscription, status=SubscriptionDelivery.Status.COMPLETED, days_ago=1)

        items = ResourceHealthSource().gather(self.team, None, period_days=7)

        assert len(items) == 1
        item = items[0]
        assert item.kind == "health"
        assert "Weekly report" in item.title
        assert item.numbers["failed_deliveries"] == 2
        assert item.evidence == [{"type": "subscription", "ref": str(subscription.id), "label": "Weekly report"}]
        assert item.fingerprint_hint == f"health:subscription:{subscription.id}"

    @parameterized.expand(
        [
            ("out_of_period", SubscriptionDelivery.Status.FAILED, 8.0),
            ("completed_in_period", SubscriptionDelivery.Status.COMPLETED, 1.0),
            ("skipped_in_period", SubscriptionDelivery.Status.SKIPPED, 1.0),
        ]
    )
    def test_non_failing_deliveries_ignored(self, _name: str, status: str, days_ago: float) -> None:
        self._delivery(self._subscription(), status=status, days_ago=days_ago)

        assert ResourceHealthSource().gather(self.team, None, period_days=7) == []

    def test_deleted_subscription_failures_ignored(self) -> None:
        subscription = self._subscription()
        subscription.deleted = True
        subscription.save()
        self._delivery(subscription)

        assert ResourceHealthSource().gather(self.team, None, period_days=7) == []

    def test_stuck_insight_refresh_yields_health_item(self) -> None:
        insight = self._insight()
        dashboard = Dashboard.objects.create(team=self.team, name="Main")
        tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        self._caching_state(insight, refresh_attempt=STUCK_REFRESH_ATTEMPTS)
        self._caching_state(insight, refresh_attempt=STUCK_REFRESH_ATTEMPTS + 1, dashboard_tile=tile)

        items = ResourceHealthSource().gather(self.team, None, period_days=7)

        assert len(items) == 1
        item = items[0]
        assert item.kind == "health"
        assert "Signup funnel" in item.title
        assert item.evidence == [{"type": "insight", "ref": insight.short_id, "label": "Signup funnel"}]
        assert item.fingerprint_hint == f"health:insight:{insight.short_id}"

    def test_below_threshold_refresh_attempts_ignored(self) -> None:
        self._caching_state(self._insight(), refresh_attempt=STUCK_REFRESH_ATTEMPTS - 1)

        assert ResourceHealthSource().gather(self.team, None, period_days=7) == []

    def test_one_failing_detector_does_not_kill_gather(self) -> None:
        self._delivery(self._subscription())

        def _boom(source: ResourceHealthSource, team: Any, period_days: int) -> list:
            raise RuntimeError("db exploded")

        with patch.object(ResourceHealthSource, "_errored_alerts", _boom):
            items = ResourceHealthSource().gather(self.team, None, period_days=7)

        assert [item.fingerprint_hint.split(":")[1] for item in items] == ["subscription"]
