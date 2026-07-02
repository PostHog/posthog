from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource, score_movement

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


class TestScoreMovement:
    @parameterized.expand(
        [
            (
                "big_drop",
                [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
                [70.0, 68.0, 71.0, 69.0, 70.0, 72.0, 70.0],
                True,
                -30.1,
            ),
            ("flat", [100.0] * 7, [101.0, 99.0, 100.0, 100.0, 100.0, 101.0, 99.0], False, 0.0),
            ("big_spike", [50.0] * 7, [80.0] * 7, True, 60.0),
            ("below_volume_floor", [2.0] * 7, [5.0] * 7, False, 150.0),
        ]
    )
    def test_score_movement(
        self,
        _name: str,
        baseline: list[float],
        current: list[float],
        expect_significant: bool,
        expect_pct_approx: float,
    ) -> None:
        movement = score_movement(baseline=baseline, current=current)
        assert movement.significant == expect_significant
        if expect_significant:
            assert abs(movement.pct_change - expect_pct_approx) < 1.0

    def test_empty_series_not_significant(self) -> None:
        movement = score_movement(baseline=[], current=[])
        assert movement.significant is False


class TestAnchoredInsightsGather(BaseTest):
    def _insight(self, name: str = "Pageviews") -> Insight:
        return Insight.objects.create(team=self.team, name=name, query=_TRENDS_QUERY)

    def _config(self, insights: list[Insight]) -> BriefConfig:
        with team_scope(self.team.pk, canonical=True):
            return BriefConfig.objects.create(
                team=self.team, name="Focus", anchors={"insights": [i.short_id for i in insights]}
            )

    @patch("products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight")
    def test_gather_returns_item_for_significant_movement(self, mock_calculate: MagicMock) -> None:
        insight = self._insight()
        config = self._config([insight])
        mock_calculate.return_value = MagicMock(result=[{"label": "$pageview", "data": [100.0] * 7 + [70.0] * 7}])

        items = AnchoredInsightsSource().gather(self.team, config, period_days=7)

        assert len(items) == 1
        assert items[0].fingerprint_hint == f"anchored_insights:{insight.short_id}:0"
        assert items[0].numbers["pct_change"] == -30.0

    @parameterized.expand(
        [
            ("non_trends_shape", [{"columns": ["count"], "results": [[42]]}], 0, None),
            ("non_significant_movement", [{"label": "x", "data": [100.0] * 14}], 0, None),
            ("odd_length_drops_oldest", [{"label": "x", "data": [999.0, 100.0, 100.0, 70.0, 70.0]}], 1, -30.0),
        ]
    )
    @patch("products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight")
    def test_gather_result_shapes(
        self,
        _name: str,
        result: list[dict],
        expected_count: int,
        expected_pct: float | None,
        mock_calculate: MagicMock,
    ) -> None:
        config = self._config([self._insight()])
        mock_calculate.return_value = MagicMock(result=result)

        items = AnchoredInsightsSource().gather(self.team, config, period_days=7)

        assert len(items) == expected_count
        if expected_pct is not None:
            assert items[0].numbers["pct_change"] == expected_pct

    @patch("products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight")
    def test_gather_survives_one_broken_insight(self, mock_calculate: MagicMock) -> None:
        broken = self._insight("Broken")
        working = self._insight("Working")
        config = self._config([broken, working])

        def _calculate(insight: Insight, **kwargs) -> MagicMock:
            if insight.id == broken.id:
                raise RuntimeError("query exploded")
            return MagicMock(result=[{"label": "x", "data": [100.0] * 7 + [70.0] * 7}])

        mock_calculate.side_effect = _calculate

        items = AnchoredInsightsSource().gather(self.team, config, period_days=7)

        assert [item.fingerprint_hint for item in items] == [f"anchored_insights:{working.short_id}:0"]

    @patch("products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight")
    def test_zero_config_falls_back_to_recent_dashboards(self, mock_calculate: MagicMock) -> None:
        insight = self._insight()
        dashboard = Dashboard.objects.create(team=self.team, name="Main", last_accessed_at=timezone.now())
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [100.0] * 7 + [70.0] * 7}])

        items = AnchoredInsightsSource().gather(self.team, None, period_days=7)

        assert [item.fingerprint_hint for item in items] == [f"anchored_insights:{insight.short_id}:0"]
