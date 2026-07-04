import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.accountability import (
    MAX_STATUS_LINES,
    METRIC_UNAVAILABLE,
    MIN_AGE_DAYS,
    OpportunityStatusLine,
    collect_accountability,
)
from products.pulse.backend.models import Opportunity

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}

_BASELINE = {"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0, "period_days": 7}

_CALCULATE_PATH = "products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight"


class TestCollectAccountability(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Signups", query=_TRENDS_QUERY)

    def _opportunity(self, created_days_ago: int = MIN_AGE_DAYS + 3, **overrides: Any) -> Opportunity:
        defaults: dict[str, Any] = {
            "team": self.team,
            "kind": Opportunity.Kind.BUILD,
            "title": "Recover the signup drop",
            "summary": "s",
            "metric_ref": {"insight_short_id": self.insight.short_id},
            "baseline": dict(_BASELINE),
            "fingerprint": f"build:{uuid.uuid4()}",
        }
        defaults.update(overrides)
        opportunity = Opportunity.objects.for_team(self.team.pk).create(**defaults)
        # created_at is auto-set — a queryset update is the only way to backdate it.
        Opportunity.objects.for_team(self.team.pk).filter(id=opportunity.id).update(
            created_at=timezone.now() - timedelta(days=created_days_ago)
        )
        return opportunity

    @patch(_CALCULATE_PATH)
    def test_status_line_recomputes_delta_against_creation_baseline(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 7 + [100.0] * 7}])
        opportunity = self._opportunity(created_days_ago=MIN_AGE_DAYS + 3)

        lines = collect_accountability(self.team)

        assert lines == [
            OpportunityStatusLine(
                opportunity_id=str(opportunity.id),
                kind="build",
                status="open",
                title="Recover the signup drop",
                age_days=MIN_AGE_DAYS + 3,
                baseline_summary="70.0/day avg",
                current_summary="100.0/day avg",
                delta_pct=42.9,
            )
        ]

    @parameterized.expand(
        [
            ("younger_than_min_age", MIN_AGE_DAYS - 1, 0),
            ("at_min_age", MIN_AGE_DAYS, 1),
            ("much_older", MIN_AGE_DAYS + 30, 1),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_age_gate(self, _name: str, created_days_ago: int, expected_count: int, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])
        self._opportunity(created_days_ago=created_days_ago)

        assert len(collect_accountability(self.team)) == expected_count

    @parameterized.expand(
        [
            ("no_metric_ref", {"metric_ref": None}),
            ("no_baseline", {"baseline": None}),
            ("metric_ref_without_short_id", {"metric_ref": {"series_index": 0}}),
            ("baseline_without_current_total", {"baseline": {"period_days": 7}}),
            ("baseline_without_period_days", {"baseline": {"current_total": 490.0}}),
            ("baseline_with_zero_period_days", {"baseline": {"current_total": 490.0, "period_days": 0}}),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_unusable_refs_are_skipped_entirely(
        self, _name: str, overrides: dict[str, Any], mock_calculate: MagicMock
    ) -> None:
        self._opportunity(**overrides)

        assert collect_accountability(self.team) == []
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("missing_insight", {"metric_ref": {"insight_short_id": "gone1234"}}, None),
            ("non_trends_shape", {}, [{"columns": ["count"], "results": [[42]]}]),
            ("series_index_out_of_range", {"metric_ref_series_index": 5}, [{"label": "x", "data": [70.0] * 14}]),
            ("too_little_data", {}, [{"label": "x", "data": [100.0]}]),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_unreadable_metric_yields_line_without_numbers(
        self,
        _name: str,
        overrides: dict[str, Any],
        result: list[dict] | None,
        mock_calculate: MagicMock,
    ) -> None:
        series_index = overrides.pop("metric_ref_series_index", None)
        if series_index is not None:
            overrides["metric_ref"] = {"insight_short_id": self.insight.short_id, "series_index": series_index}
        mock_calculate.return_value = MagicMock(result=result)
        self._opportunity(**overrides)

        lines = collect_accountability(self.team)

        assert len(lines) == 1
        assert lines[0].baseline_summary == "70.0/day avg"
        assert lines[0].current_summary == METRIC_UNAVAILABLE
        assert lines[0].delta_pct is None

    @patch(_CALCULATE_PATH)
    def test_deleted_insight_yields_line_without_numbers(self, mock_calculate: MagicMock) -> None:
        self.insight.deleted = True
        self.insight.save()
        self._opportunity()

        lines = collect_accountability(self.team)

        assert len(lines) == 1
        assert lines[0].current_summary == METRIC_UNAVAILABLE
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_zero_baseline_yields_no_delta(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])
        self._opportunity(baseline={"current_total": 0.0, "period_days": 7})

        lines = collect_accountability(self.team)

        assert lines[0].delta_pct is None
        assert lines[0].baseline_summary == "0.0/day avg"
        assert lines[0].current_summary == "70.0/day avg"

    @patch(_CALCULATE_PATH)
    def test_series_index_selects_the_right_series(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(
            result=[{"label": "a", "data": [10.0] * 14}, {"label": "b", "data": [70.0] * 7 + [100.0] * 7}]
        )
        self._opportunity(metric_ref={"insight_short_id": self.insight.short_id, "series_index": 1})

        lines = collect_accountability(self.team)

        assert lines[0].current_summary == "100.0/day avg"

    @patch(_CALCULATE_PATH)
    def test_every_lifecycle_status_gets_a_line(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])
        for opportunity_status in Opportunity.Status.values:
            self._opportunity(status=opportunity_status)

        lines = collect_accountability(self.team)

        assert sorted(line.status for line in lines) == sorted(Opportunity.Status.values)

    @patch(_CALCULATE_PATH)
    def test_capped_newest_first(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])
        for i in range(MAX_STATUS_LINES + 2):
            self._opportunity(title=f"opp-{i}", created_days_ago=MIN_AGE_DAYS + i)

        lines = collect_accountability(self.team)

        assert [line.title for line in lines] == [f"opp-{i}" for i in range(MAX_STATUS_LINES)]

    @patch(_CALCULATE_PATH)
    def test_one_broken_rescore_does_not_blank_the_others(self, mock_calculate: MagicMock) -> None:
        other_insight = Insight.objects.create(team=self.team, name="Broken", query=_TRENDS_QUERY)

        def _calculate(insight: Insight, **kwargs: Any) -> MagicMock:
            if insight.id == other_insight.id:
                raise RuntimeError("query exploded")
            return MagicMock(result=[{"label": "x", "data": [70.0] * 14}])

        mock_calculate.side_effect = _calculate
        self._opportunity(title="healthy")
        self._opportunity(title="broken", metric_ref={"insight_short_id": other_insight.short_id})

        lines = collect_accountability(self.team)

        assert [line.title for line in lines] == ["healthy"]

    @patch(_CALCULATE_PATH)
    def test_other_team_opportunities_excluded(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(result=[{"label": "x", "data": [70.0] * 14}])
        other_team = Team.objects.create(organization=self.organization, name="Other")
        opportunity = self._opportunity()
        Opportunity.objects.for_team(other_team.pk).create(
            team=other_team,
            kind=Opportunity.Kind.BUILD,
            title="Other team",
            summary="s",
            metric_ref={"insight_short_id": self.insight.short_id},
            baseline=dict(_BASELINE),
            fingerprint=f"build:{uuid.uuid4()}",
        )

        lines = collect_accountability(self.team)

        assert [line.opportunity_id for line in lines] == [str(opportunity.id)]
