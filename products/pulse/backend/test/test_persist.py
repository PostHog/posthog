from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.accountability import MAX_STATUS_LINES
from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut, ProposedExperimentOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.anchored_insights import InsightResultsCache
from products.pulse.backend.sources.base import SourceItem

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}

_CALCULATE_PATH = "products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight"


def _proposed_experiment(target_short_id: str = "abc") -> ProposedExperimentOut:
    return ProposedExperimentOut(
        hypothesis="Moving the entry point above the fold lifts subscription creation",
        flag_key_suggestion="subscription-entry-point",
        target_metric_insight_short_id=target_short_id,
        variant_sketch="Control keeps the sidebar entry; test adds a button above the insights list.",
    )


def _out(
    fingerprint_hint: str = "abc:0",
    goal_relevant: bool = False,
    proposed_experiment: ProposedExperimentOut | None = None,
    evidence_refs: list[str] | None = None,
) -> BriefOut:
    return BriefOut(
        sections=[
            BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["insight:abc"], confidence=0.9)
        ],
        opportunities=[
            OpportunityOut(
                kind="build",
                title="t",
                summary="s",
                suggested_action="a",
                evidence_refs=evidence_refs if evidence_refs is not None else ["insight:abc"],
                fingerprint_hint=fingerprint_hint,
                confidence=0.9,
                goal_relevant=goal_relevant,
                proposed_experiment=proposed_experiment,
            )
        ],
    )


def _item(fingerprint_hint: str = "abc:0") -> SourceItem:
    return SourceItem(
        source="anchored_insights",
        kind="movement",
        title="Pageviews dropped 30%",
        description="d",
        numbers={"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0},
        evidence=[{"type": "insight", "ref": "abc", "label": "Pageviews"}],
        fingerprint_hint=fingerprint_hint,
    )


class TestPersistBriefOutput(BaseTest):
    def _brief(self) -> ProductBrief:
        return ProductBrief.objects.for_team(self.team.pk).create(
            team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
        )

    def _opportunities(self):
        return Opportunity.objects.for_team(self.team.pk)

    def test_persists_sections_and_resolved_opportunity_context(self) -> None:
        brief = self._brief()
        created = persist_brief_output(brief=brief, out=_out(goal_relevant=True), items=[_item()])
        assert brief.status == ProductBrief.Status.READY
        assert len(brief.sections) == 1
        assert brief.sources_used == ["anchored_insights"]
        opportunity = self._opportunities().get()
        assert [o.id for o in created] == [opportunity.id]
        assert opportunity.evidence == [{"type": "insight", "ref": "abc", "label": "Pageviews"}]
        assert opportunity.baseline == {"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0}
        assert opportunity.metric_ref == {"insight_short_id": "abc"}
        assert opportunity.goal_relevant is True

    @patch(_CALCULATE_PATH)
    def test_goal_relevant_proposed_experiment_roundtrips_to_the_stored_shape(self, mock_calculate: MagicMock) -> None:
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment())
        persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        opportunity = self._opportunities().get()
        assert opportunity.proposed_experiment == {
            "hypothesis": "Moving the entry point above the fold lifts subscription creation",
            "flag_key_suggestion": "subscription-entry-point",
            "target_metric": {"insight_short_id": "abc"},
            "variant_sketch": "Control keeps the sidebar entry; test adds a button above the insights list.",
        }
        # The item resolved a metric of its own — promotion must not touch it or run an insight.
        assert opportunity.metric_ref == {"insight_short_id": "abc"}
        assert opportunity.baseline == _item().numbers
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_promotes_validated_target_metric_for_metricless_opportunity(self, mock_calculate: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        mock_calculate.return_value = MagicMock(result=[{"data": [1.0] * 7 + [2.0] * 7}])
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref == {"insight_short_id": insight.short_id}
        assert opportunity.baseline == {"current_total": 14.0, "period_days": 7}
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": insight.short_id}

    @patch(_CALCULATE_PATH)
    def test_invented_target_metric_on_fallback_path_is_dropped_and_never_promoted(
        self, mock_calculate: MagicMock
    ) -> None:
        # No item resolved, so the LLM-authored evidence refs cite the invented id too — only
        # the server-side insight resolution can reject it.
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment("zzz9"),
            evidence_refs=["insight:zzz9"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        assert opportunity.proposed_experiment["target_metric"] is None
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_uncited_target_metric_on_item_path_is_dropped(self, mock_calculate: MagicMock) -> None:
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment("other1"))
        persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        opportunity = self._opportunities().get()
        assert opportunity.proposed_experiment["target_metric"] is None
        assert opportunity.metric_ref == {"insight_short_id": "abc"}  # the item's own metric is untouched
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("execution_raises", RuntimeError("clickhouse down")),
            ("non_trends_shape", [{"no": "data"}]),
            ("too_little_data", [{"data": [1.0]}]),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_promotion_degrades_all_or_nothing(
        self, _name: str, calculation: Exception | list, mock_calculate: MagicMock
    ) -> None:
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        if isinstance(calculation, Exception):
            mock_calculate.side_effect = calculation
        else:
            mock_calculate.return_value = MagicMock(result=calculation)
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        # All-or-nothing: an unreadable snapshot must set NEITHER field, and never raise.
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": insight.short_id}

    @patch(_CALCULATE_PATH)
    def test_promotion_skips_an_insight_deleted_after_gather(self, mock_calculate: MagicMock) -> None:
        # Item path: membership passes via the gathered evidence, but the insight row is gone by
        # persist time — the promotion's own resolution is what catches it.
        item = SourceItem(
            source="anchored_insights",
            kind="movement",
            title="t",
            description="d",
            numbers={"pct_change": -30.0},
            evidence=[
                {"type": "dashboard", "ref": "7", "label": "Home"},
                {"type": "insight", "ref": "abc", "label": ""},
            ],
            fingerprint_hint="abc:0",
        )
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment("abc"))
        persist_brief_output(brief=self._brief(), out=out, items=[item])
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref is None
        assert opportunity.baseline == item.numbers
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": "abc"}
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_promotion_respects_the_shared_execution_budget(self, mock_calculate: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        spent_cache = InsightResultsCache(self.team)
        spent_cache.attempts = MAX_STATUS_LINES
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[], results_cache=spent_cache)
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("not_goal_relevant", False, _proposed_experiment()),
            ("no_proposal", True, None),
        ]
    )
    def test_proposed_experiment_is_nulled_unless_goal_relevant(
        self, _name: str, goal_relevant: bool, proposed: ProposedExperimentOut | None
    ) -> None:
        out = _out(goal_relevant=goal_relevant, proposed_experiment=proposed)
        persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        assert self._opportunities().get().proposed_experiment is None

    def test_unresolvable_ref_falls_back_to_parsed_evidence(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(fingerprint_hint="unknown:9"), items=[_item()])
        opportunity = self._opportunities().get()
        assert opportunity.evidence == [{"type": "insight", "ref": "abc", "label": ""}]
        assert opportunity.baseline is None
        assert opportunity.metric_ref is None

    def test_same_fingerprint_does_not_duplicate(self) -> None:
        first = persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        second = persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert self._opportunities().count() == 1
        assert len(first) == 1
        assert second == []

    def test_dismissed_fingerprint_is_suppressed(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        self._opportunities().update(status=Opportunity.Status.DISMISSED)
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert self._opportunities().count() == 1

    def test_empty_output_marks_quiet(self) -> None:
        brief = self._brief()
        persist_brief_output(brief=brief, out=BriefOut(sections=[], opportunities=[]), items=[])
        assert brief.status == ProductBrief.Status.QUIET
        assert brief.sources_used == []

    def test_opportunity_only_output_marks_ready(self) -> None:
        out = BriefOut(sections=[], opportunities=_out().opportunities)
        brief = self._brief()
        persist_brief_output(brief=brief, out=out, items=[_item()])
        assert brief.status == ProductBrief.Status.READY
