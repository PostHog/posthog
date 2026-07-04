from posthog.test.base import BaseTest

from parameterized import parameterized

from products.pulse.backend.generation.investigate import InvestigationFinding
from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut, ProposedExperimentOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem


def _proposed_experiment() -> ProposedExperimentOut:
    return ProposedExperimentOut(
        hypothesis="Moving the entry point above the fold lifts subscription creation",
        flag_key_suggestion="subscription-entry-point",
        target_metric_insight_short_id="abc",
        variant_sketch="Control keeps the sidebar entry; test adds a button above the insights list.",
    )


def _out(
    fingerprint_hint: str = "abc:0",
    goal_relevant: bool = False,
    proposed_experiment: ProposedExperimentOut | None = None,
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
                evidence_refs=["insight:abc"],
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
        created = persist_brief_output(brief=brief, out=_out(goal_relevant=True), items=[_item()], findings=[])
        assert brief.status == ProductBrief.Status.READY
        assert len(brief.sections) == 1
        assert brief.sources_used == ["anchored_insights"]
        opportunity = self._opportunities().get()
        assert [o.id for o in created] == [opportunity.id]
        assert opportunity.evidence == [{"type": "insight", "ref": "abc", "label": "Pageviews"}]
        assert opportunity.baseline == {"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0}
        assert opportunity.metric_ref == {"insight_short_id": "abc"}
        assert opportunity.goal_relevant is True

    def test_goal_relevant_proposed_experiment_roundtrips_to_the_stored_shape(self) -> None:
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment())
        persist_brief_output(brief=self._brief(), out=out, items=[_item()], findings=[])
        assert self._opportunities().get().proposed_experiment == {
            "hypothesis": "Moving the entry point above the fold lifts subscription creation",
            "flag_key_suggestion": "subscription-entry-point",
            "target_metric": {"insight_short_id": "abc"},
            "variant_sketch": "Control keeps the sidebar entry; test adds a button above the insights list.",
        }

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
        persist_brief_output(brief=self._brief(), out=out, items=[_item()], findings=[])
        assert self._opportunities().get().proposed_experiment is None

    def test_unresolvable_ref_falls_back_to_parsed_evidence(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(fingerprint_hint="unknown:9"), items=[_item()], findings=[])
        opportunity = self._opportunities().get()
        assert opportunity.evidence == [{"type": "insight", "ref": "abc", "label": ""}]
        assert opportunity.baseline is None
        assert opportunity.metric_ref is None

    def test_same_fingerprint_does_not_duplicate(self) -> None:
        first = persist_brief_output(brief=self._brief(), out=_out(), items=[_item()], findings=[])
        second = persist_brief_output(brief=self._brief(), out=_out(), items=[_item()], findings=[])
        assert self._opportunities().count() == 1
        assert len(first) == 1
        assert second == []

    def test_dismissed_fingerprint_is_suppressed(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()], findings=[])
        self._opportunities().update(status=Opportunity.Status.DISMISSED)
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()], findings=[])
        assert self._opportunities().count() == 1

    def test_persists_investigation_findings_in_citation_order(self) -> None:
        brief = self._brief()
        findings = [
            InvestigationFinding(question="What is the CTR?", hogql="SELECT 1", result_summary="0.42", succeeded=True),
            InvestigationFinding(
                question="Which pages?",
                hogql="SELECT 2",
                result_summary="Query failed to run (ExposedHogQLError).",
                succeeded=False,
            ),
        ]
        persist_brief_output(brief=brief, out=_out(), items=[_item()], findings=findings)
        reloaded = ProductBrief.objects.for_team(self.team.pk).get(id=brief.id)
        assert reloaded.investigation == [
            {"question": "What is the CTR?", "hogql": "SELECT 1", "result_summary": "0.42", "succeeded": True},
            {
                "question": "Which pages?",
                "hogql": "SELECT 2",
                "result_summary": "Query failed to run (ExposedHogQLError).",
                "succeeded": False,
            },
        ]

    def test_empty_output_marks_quiet(self) -> None:
        brief = self._brief()
        persist_brief_output(brief=brief, out=BriefOut(sections=[], opportunities=[]), items=[], findings=[])
        assert brief.status == ProductBrief.Status.QUIET
        assert brief.sources_used == []

    def test_opportunity_only_output_marks_ready(self) -> None:
        out = BriefOut(sections=[], opportunities=_out().opportunities)
        brief = self._brief()
        persist_brief_output(brief=brief, out=out, items=[_item()], findings=[])
        assert brief.status == ProductBrief.Status.READY
