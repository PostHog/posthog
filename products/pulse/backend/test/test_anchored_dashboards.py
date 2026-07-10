from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.scoping import team_scope

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_dashboards import AnchoredDashboardsSource
from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.strategy import MovementScoringStrategy

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}
_MOVEMENT_RESULT = [{"label": "x", "data": [100.0] * 7 + [70.0] * 7}]


class TestAnchoredDashboardsGather(BaseTest):
    def _insight(self, name: str = "Pageviews") -> Insight:
        return Insight.objects.create(team=self.team, name=name, query=_TRENDS_QUERY)

    def _source(self) -> AnchoredDashboardsSource:
        return AnchoredDashboardsSource(MovementScoringStrategy())

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_dashboard_anchored_gather(self, mock_calculate: MagicMock) -> None:
        insight = self._insight()
        dashboard = Dashboard.objects.create(team=self.team, name="Anchor")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="Focus", anchors={"dashboards": [dashboard.id]})
        mock_calculate.return_value = MagicMock(result=_MOVEMENT_RESULT)

        items = self._source().gather(self.team, config, lookback_days=7)

        assert [item.fingerprint_hint for item in items] == [f"{insight.short_id}:0"]
        assert items[0].source == "anchored_dashboards"

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_zero_config_falls_back_to_recent_dashboards(self, mock_calculate: MagicMock) -> None:
        insight = self._insight()
        dashboard = Dashboard.objects.create(team=self.team, name="Main", last_accessed_at=timezone.now())
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        mock_calculate.return_value = MagicMock(result=_MOVEMENT_RESULT)

        items = self._source().gather(self.team, None, lookback_days=7)

        assert [item.fingerprint_hint for item in items] == [f"{insight.short_id}:0"]

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_insight_only_anchors_gather_nothing_from_dashboards_source(self, mock_calculate: MagicMock) -> None:
        # With insight anchors but no dashboard anchors, the dashboards source must not also pull
        # the zero-config fallback — otherwise the same movements would be double-gathered.
        insight = self._insight()
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="Focus", anchors={"insights": [insight.short_id]})

        items = self._source().gather(self.team, config, lookback_days=7)

        assert items == []
        mock_calculate.assert_not_called()

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_both_sources_score_the_same_insight_identically(self, mock_calculate: MagicMock) -> None:
        # The shared strategy means the insights source and the dashboards source produce the same
        # scored movement for one insight — only the source tag and retrieval path differ.
        strategy = MovementScoringStrategy()
        insight = self._insight()
        dashboard = Dashboard.objects.create(team=self.team, name="D")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        with team_scope(self.team.pk, canonical=True):
            insight_config = BriefConfig.objects.create(
                team=self.team, name="I", anchors={"insights": [insight.short_id]}
            )
            dashboard_config = BriefConfig.objects.create(
                team=self.team, name="D", anchors={"dashboards": [dashboard.id]}
            )
        mock_calculate.return_value = MagicMock(result=_MOVEMENT_RESULT)

        from_insights = AnchoredInsightsSource(strategy).gather(self.team, insight_config, lookback_days=7)
        from_dashboards = AnchoredDashboardsSource(strategy).gather(self.team, dashboard_config, lookback_days=7)

        assert len(from_insights) == len(from_dashboards) == 1
        assert from_insights[0].metrics == from_dashboards[0].metrics
        assert from_insights[0].fingerprint_hint == from_dashboards[0].fingerprint_hint
