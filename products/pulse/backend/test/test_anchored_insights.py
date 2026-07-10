from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.config import DEFAULT_BRIEF_SETTINGS, BriefSettings
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.strategy import MovementScoringStrategy, score_movement

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
        movement = score_movement(baseline=baseline, current=current, settings=DEFAULT_BRIEF_SETTINGS)
        assert movement.significant == expect_significant
        if expect_significant:
            assert abs(movement.pct_change - expect_pct_approx) < 1.0

    def test_empty_series_not_significant(self) -> None:
        movement = score_movement(baseline=[], current=[], settings=DEFAULT_BRIEF_SETTINGS)
        assert movement.significant is False

    def test_settings_override_changes_significance(self) -> None:
        # A 10% move is below the default 20% threshold but above a lowered one — the knob decides.
        baseline, current = [100.0] * 7, [90.0] * 7
        assert score_movement(baseline=baseline, current=current, settings=DEFAULT_BRIEF_SETTINGS).significant is False
        lowered = BriefSettings.from_config(BriefConfig(settings={"min_abs_change_pct": 5.0}))
        assert score_movement(baseline=baseline, current=current, settings=lowered).significant is True


class TestAnchoredInsightsGather(BaseTest):
    def _insight(self, name: str = "Pageviews") -> Insight:
        return Insight.objects.create(team=self.team, name=name, query=_TRENDS_QUERY)

    def _config(self, insights: list[Insight]) -> BriefConfig:
        with team_scope(self.team.pk, canonical=True):
            return BriefConfig.objects.create(
                team=self.team, name="Focus", anchors={"insights": [i.short_id for i in insights]}
            )

    def _source(self) -> AnchoredInsightsSource:
        return AnchoredInsightsSource(MovementScoringStrategy())

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_gather_returns_item_for_significant_movement(self, mock_calculate: MagicMock) -> None:
        insight = self._insight()
        config = self._config([insight])
        mock_calculate.return_value = MagicMock(result=[{"label": "$pageview", "data": [100.0] * 7 + [70.0] * 7}])

        items = self._source().gather(self.team, config, lookback_days=7)

        assert len(items) == 1
        assert items[0].source == "anchored_insights"
        assert items[0].fingerprint_hint == f"{insight.short_id}:0"
        assert items[0].metrics["pct_change"] == -30.0
        # Evidence carries a navigable deep link into the app.
        assert items[0].evidence[0]["url"] == f"/project/{self.team.id}/insights/{insight.short_id}"

    @parameterized.expand(
        [
            ("non_trends_shape", [{"columns": ["count"], "results": [[42]]}], 0, None),
            ("non_significant_movement", [{"label": "x", "data": [100.0] * 14}], 0, None),
            ("odd_length_drops_oldest", [{"label": "x", "data": [999.0, 100.0, 100.0, 70.0, 70.0]}], 1, -30.0),
        ]
    )
    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
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

        items = self._source().gather(self.team, config, lookback_days=7)

        assert len(items) == expected_count
        if expected_pct is not None:
            assert items[0].metrics["pct_change"] == expected_pct

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_gather_survives_one_broken_insight(self, mock_calculate: MagicMock) -> None:
        broken = self._insight("Broken")
        working = self._insight("Working")
        config = self._config([broken, working])

        def _calculate(insight: Insight, **kwargs) -> MagicMock:
            if insight.id == broken.id:
                raise RuntimeError("query exploded")
            return MagicMock(result=[{"label": "x", "data": [100.0] * 7 + [70.0] * 7}])

        mock_calculate.side_effect = _calculate

        items = self._source().gather(self.team, config, lookback_days=7)

        assert [item.fingerprint_hint for item in items] == [f"{working.short_id}:0"]

    @patch("products.pulse.backend.sources.strategy.calculate_for_query_based_insight")
    def test_dashboard_anchors_are_not_gathered_by_insights_source(self, mock_calculate: MagicMock) -> None:
        # A dashboard-only anchored config yields nothing from the insights source — dashboards are
        # the dashboards source's job. This is the split under test.
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="Focus", anchors={"dashboards": [1]})

        items = self._source().gather(self.team, config, lookback_days=7)

        assert items == []
        mock_calculate.assert_not_called()
