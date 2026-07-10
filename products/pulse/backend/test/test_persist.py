from posthog.test.base import BaseTest

from posthog.models.scoping import team_scope

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import (
    ActionStatus,
    ActionType,
    Opportunity,
    ProductBrief,
    ResourceLink,
    ResourceType,
)
from products.pulse.backend.sources.base import SourceItem

_EVIDENCE = {"type": "insight", "ref": "abc", "label": "Pageviews", "url": "/project/1/insights/abc"}


def _out(fingerprint_hint: str = "abc:0", evidence_refs: list[str] | None = None) -> BriefOut:
    refs = ["c1"] if evidence_refs is None else evidence_refs
    return BriefOut(
        sections=[BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["c1"], confidence=0.9)],
        opportunities=[
            OpportunityOut(
                kind="build",
                title="t",
                summary="s",
                suggested_action="a",
                evidence_refs=refs,
                fingerprint_hint=fingerprint_hint,
                confidence=0.9,
            )
        ],
    )


def _item(fingerprint_hint: str = "abc:0") -> SourceItem:
    return SourceItem(
        source="anchored_insights",
        kind="movement",
        title="Pageviews dropped 30%",
        description="d",
        metrics={"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0},
        evidence=[_EVIDENCE],
        fingerprint_hint=fingerprint_hint,
    )


class TestPersistBriefOutput(BaseTest):
    def _brief(self) -> ProductBrief:
        return ProductBrief.objects.for_team(self.team.pk).create(
            team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND
        )

    def _opportunities(self):
        return Opportunity.objects.for_team(self.team.pk)

    def _links(self):
        return ResourceLink.objects.for_team(self.team.pk)

    def test_resolves_citation_ids_to_resource_links_and_action(self) -> None:
        # A real insight with the cited short_id so the link resolves its FK.
        with team_scope(self.team.pk, canonical=True):
            insight = Insight.objects.create(team=self.team, name="Pageviews", short_id="abc")
        brief = persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert brief.status == ProductBrief.Status.READY
        assert len(brief.sections) == 1
        assert brief.sources_used == ["anchored_insights"]
        opportunity = self._opportunities().get()
        assert opportunity.baseline == {"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0}
        assert opportunity.metric_ref == {"insight_short_id": "abc"}
        # The LLM summary is wrapped in the structured advisory action envelope.
        assert opportunity.action == {
            "type": ActionType.ADVISORY.value,
            "summary": "a",
            "params": {},
            "status": ActionStatus.PROPOSED.value,
        }
        # The cited id 'c1' resolves to a ResourceLink with the right type, cached columns, and FK.
        link = self._links().get()
        assert link.resource_type == ResourceType.INSIGHT
        assert link.ref == "abc"
        assert link.label == "Pageviews"
        assert link.url == "/project/1/insights/abc"
        assert link.insight_id == insight.id

    def test_link_created_even_when_insight_ref_does_not_resolve(self) -> None:
        # No insight with short_id 'abc' exists — the link is still created (cached columns only),
        # with a null FK, so a deleted/renamed resource does not drop the evidence.
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        link = self._links().get()
        assert link.resource_type == ResourceType.INSIGHT
        assert link.ref == "abc"
        assert link.insight_id is None

    def test_unknown_citation_id_creates_no_link(self) -> None:
        # The model cited an id that maps to no gathered evidence — it is dropped, not fabricated.
        persist_brief_output(brief=self._brief(), out=_out(evidence_refs=["c1", "c99"]), items=[_item()])
        assert self._opportunities().count() == 1
        assert [link.ref for link in self._links()] == ["abc"]

    def test_same_fingerprint_does_not_duplicate(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert self._opportunities().count() == 1

    def test_dismissed_fingerprint_is_suppressed(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        self._opportunities().update(status=Opportunity.Status.DISMISSED)
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert self._opportunities().count() == 1

    def test_empty_output_marks_quiet(self) -> None:
        brief = persist_brief_output(brief=self._brief(), out=BriefOut(sections=[], opportunities=[]), items=[])
        assert brief.status == ProductBrief.Status.QUIET
        assert brief.sources_used == []

    def test_opportunity_only_output_marks_ready(self) -> None:
        out = BriefOut(sections=[], opportunities=_out().opportunities)
        brief = persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        assert brief.status == ProductBrief.Status.READY
