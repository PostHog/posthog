from posthog.test.base import BaseTest

from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief


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
            )
        ],
    )


class TestPersistBriefOutput(BaseTest):
    def _brief(self) -> ProductBrief:
        return ProductBrief.objects.for_team(self.team.pk).create(
            team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
        )

    def _opportunities(self):
        return Opportunity.objects.for_team(self.team.pk)

    def test_persists_sections_and_opportunities(self) -> None:
        brief = persist_brief_output(brief=self._brief(), out=_out())
        assert brief.status == ProductBrief.Status.READY
        assert len(brief.sections) == 1
        assert self._opportunities().count() == 1

    def test_same_fingerprint_does_not_duplicate(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out())
        persist_brief_output(brief=self._brief(), out=_out())
        assert self._opportunities().count() == 1

    def test_dismissed_fingerprint_is_suppressed(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out())
        self._opportunities().update(status=Opportunity.Status.DISMISSED)
        persist_brief_output(brief=self._brief(), out=_out())
        assert self._opportunities().count() == 1

    def test_empty_output_marks_quiet(self) -> None:
        brief = persist_brief_output(brief=self._brief(), out=BriefOut(sections=[], opportunities=[]))
        assert brief.status == ProductBrief.Status.QUIET
