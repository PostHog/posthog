from posthog.test.base import BaseTest

from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem


def _out(fingerprint_hint: str = "abc:0") -> BriefOut:
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
                goal_relevant=False,
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
        created = persist_brief_output(brief=brief, out=_out(), items=[_item()])
        assert brief.status == ProductBrief.Status.READY
        assert len(brief.sections) == 1
        assert brief.sources_used == ["anchored_insights"]
        opportunity = self._opportunities().get()
        assert [o.id for o in created] == [opportunity.id]
        assert opportunity.evidence == [{"type": "insight", "ref": "abc", "label": "Pageviews"}]
        assert opportunity.baseline == {"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0}
        assert opportunity.metric_ref == {"insight_short_id": "abc"}

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
