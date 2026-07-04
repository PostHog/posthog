from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.goal import GoalStatus, collect_goal_status
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import InsightResultsCache

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}

_CALCULATE_PATH = "products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight"


class TestCollectGoalStatus(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)

    def _config(self, **overrides: Any) -> BriefConfig:
        defaults: dict[str, Any] = {
            "team": self.team,
            "name": "Subscriptions focus",
            "goal": "Increase subscription usage",
            "goal_metric": {"insight_short_id": self.insight.short_id},
        }
        defaults.update(overrides)
        with team_scope(self.team.pk, canonical=True):
            return BriefConfig.objects.create(**defaults)

    @patch(_CALCULATE_PATH)
    def test_metric_yields_rates_and_delta_from_shared_window_math(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 7 + [100.0] * 7}])

        status = collect_goal_status(self.team, self._config(), 7)

        assert status == GoalStatus(
            goal="Increase subscription usage",
            metric_state="ok",
            insight_short_id=self.insight.short_id,
            metric_label="Subscriptions created",
            current_rate="100.0/day avg",
            previous_rate="70.0/day avg",
            delta_pct=42.9,
        )

    @parameterized.expand([("empty", ""), ("whitespace_only", "   \n ")])
    @patch(_CALCULATE_PATH)
    def test_blank_goal_yields_none(self, _name: str, goal: str, mock_calculate: MagicMock) -> None:
        assert collect_goal_status(self.team, self._config(goal=goal), 7) is None
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("no_metric", {"goal_metric": None}),
            ("metric_not_a_dict", {"goal_metric": "abc"}),
            ("metric_without_short_id", {"goal_metric": {"series_index": 0}}),
            ("metric_with_blank_short_id", {"goal_metric": {"insight_short_id": ""}}),
            ("metric_with_non_string_short_id", {"goal_metric": {"insight_short_id": 42}}),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_unusable_metric_ref_skips_execution(
        self, _name: str, overrides: dict[str, Any], mock_calculate: MagicMock
    ) -> None:
        status = collect_goal_status(self.team, self._config(**overrides), 7)

        # metric_state defaults to "none": a malformed ref degrades to a qualitative goal.
        assert status == GoalStatus(goal="Increase subscription usage")
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("missing_insight", "gone1234", []),
            ("empty_results", None, []),
            ("non_trends_shape", None, [{"columns": ["count"], "results": [[42]]}]),
            ("too_little_data", None, [{"label": "x", "data": [100.0]}]),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_unreadable_metric_degrades_to_unavailable(
        self, _name: str, short_id: str | None, result: list[dict], mock_calculate: MagicMock
    ) -> None:
        mock_calculate.return_value = MagicMock(result=result)
        config = self._config(**({"goal_metric": {"insight_short_id": short_id}} if short_id else {}))

        status = collect_goal_status(self.team, config, 7)

        assert status is not None
        assert status.goal == "Increase subscription usage"
        assert status.metric_state == "unavailable"
        assert status.insight_short_id == (short_id or self.insight.short_id)
        assert status.metric_label is None
        assert status.current_rate is None
        assert status.previous_rate is None
        assert status.delta_pct is None

    @patch(_CALCULATE_PATH)
    def test_failing_execution_degrades_to_unavailable(self, mock_calculate: MagicMock) -> None:
        mock_calculate.side_effect = RuntimeError("query exploded")

        status = collect_goal_status(self.team, self._config(), 7)

        assert status is not None
        assert status.metric_state == "unavailable"
        assert status.current_rate is None

    @patch(_CALCULATE_PATH)
    def test_deleted_insight_degrades_without_execution(self, mock_calculate: MagicMock) -> None:
        self.insight.deleted = True
        self.insight.save()

        status = collect_goal_status(self.team, self._config(), 7)

        assert status is not None
        assert status.metric_state == "unavailable"
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_other_team_insight_is_not_read(self, mock_calculate: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        foreign_insight = Insight.objects.create(team=other_team, name="Foreign", query=_TRENDS_QUERY)

        status = collect_goal_status(
            self.team, self._config(goal_metric={"insight_short_id": foreign_insight.short_id}), 7
        )

        assert status is not None
        assert status.metric_state == "unavailable"
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_zero_previous_rate_yields_no_delta(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [0.0] * 7 + [100.0] * 7}])

        status = collect_goal_status(self.team, self._config(), 7)

        assert status is not None
        assert status.current_rate == "100.0/day avg"
        assert status.previous_rate == "0.0/day avg"
        assert status.delta_pct is None

    @patch(_CALCULATE_PATH)
    def test_goal_text_is_stripped_but_not_sanitized(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])

        status = collect_goal_status(self.team, self._config(goal="  grow <fast>\n  "), 7)

        # Sanitization happens once at the prompt-render boundary — the collector stays raw.
        assert status is not None
        assert status.goal == "grow <fast>"

    @patch(_CALCULATE_PATH)
    def test_shared_results_cache_prevents_reexecution(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])
        cache = InsightResultsCache(self.team)

        collect_goal_status(self.team, self._config(), 7, results_cache=cache)
        collect_goal_status(self.team, self._config(), 7, results_cache=cache)

        mock_calculate.assert_called_once()
