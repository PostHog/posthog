from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource, score_movement


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
    @patch("products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight")
    def test_gather_returns_item_for_significant_movement(self, mock_calculate: MagicMock) -> None:
        insight = Insight.objects.create(
            team=self.team,
            name="Pageviews",
            query={
                "kind": "InsightVizNode",
                "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="Focus", anchors={"insights": [insight.short_id]})
        mock_calculate.return_value = MagicMock(result=[{"label": "$pageview", "data": [100.0] * 7 + [70.0] * 7}])

        items = AnchoredInsightsSource().gather(self.team, config, period_days=7)

        assert len(items) == 1
        assert items[0].fingerprint_hint == f"{insight.short_id}:0"
        assert items[0].numbers["pct_change"] == -30.0
