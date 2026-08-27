from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.ai_subscription.anchor_context import (
    ANCHOR_TILES_LIMIT,
    build_anchor_context,
)
from products.product_analytics.backend.facade.models import Insight

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "export created"}]},
}


class TestBuildAnchorContext(APIBaseTest):
    def _subscription(self, **kwargs) -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            prompt="how are exports doing?",
            target_type="email",
            target_value="a@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            **kwargs,
        )

    def test_no_anchor_returns_none(self) -> None:
        assert build_anchor_context(self._subscription()) is None

    def test_dashboard_anchor_lists_tiles_in_layout_order_with_queries(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Growth", description="North star")
        bottom = Insight.objects.create(team=self.team, name="Signups", query=_TRENDS_QUERY)
        top = Insight.objects.create(team=self.team, name="Pageviews")
        DashboardTile.objects.create(dashboard=dashboard, insight=bottom, layouts={"sm": {"x": 0, "y": 5}})
        DashboardTile.objects.create(dashboard=dashboard, insight=top, layouts={"sm": {"x": 0, "y": 0}})

        context = build_anchor_context(self._subscription(anchor_dashboard=dashboard))

        assert context is not None
        assert "Anchored dashboard" in context.blob
        assert "Growth" in context.blob and "North star" in context.blob
        # Layout order, not creation order.
        assert context.blob.index("Pageviews") < context.blob.index("Signups")
        assert "export created" in context.blob
        assert context.event_names == ["export created"]

    def test_deleted_tiles_and_over_limit_tiles_are_excluded(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Big")
        for i in range(ANCHOR_TILES_LIMIT + 2):
            insight = Insight.objects.create(team=self.team, name=f"insight-{i}")
            DashboardTile.objects.create(dashboard=dashboard, insight=insight, layouts={"sm": {"x": 0, "y": i}})
        deleted = Insight.objects.create(team=self.team, name="ghost", deleted=True)
        DashboardTile.objects.create(dashboard=dashboard, insight=deleted, layouts={"sm": {"x": 0, "y": 99}})

        context = build_anchor_context(self._subscription(anchor_dashboard=dashboard))

        assert context is not None
        assert "ghost" not in context.blob
        assert "2 more tiles not shown" in context.blob

    def test_insight_anchor_and_hash_tracks_content(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Signups", query=_TRENDS_QUERY)
        subscription = self._subscription(anchor_insight=insight)

        context = build_anchor_context(subscription)
        assert context is not None
        assert "Anchored insight" in context.blob
        assert "Signups" in context.blob

        # Content change means a different hash, which is what invalidates a frozen plan.
        insight.name = "Signups by week"
        insight.save()
        subscription.refresh_from_db()
        changed = build_anchor_context(subscription)
        assert changed is not None
        assert changed.content_hash != context.content_hash

    def test_soft_deleted_anchor_degrades_to_none(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Gone", deleted=True)
        assert build_anchor_context(self._subscription(anchor_dashboard=dashboard)) is None
