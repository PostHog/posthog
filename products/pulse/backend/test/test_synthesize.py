from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.generation.synthesize import CONFIDENCE_THRESHOLD, apply_say_less_gate, synthesize_brief


def _section(confidence: float) -> BriefSectionOut:
    return BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["ins:abc"], confidence=confidence)


def _opportunity(confidence: float) -> OpportunityOut:
    return OpportunityOut(
        kind="build",
        title="t",
        summary="s",
        suggested_action="a",
        evidence_refs=["ins:abc"],
        fingerprint_hint="abc:0",
        confidence=confidence,
    )


class TestSayLessGate:
    @parameterized.expand(
        [
            ("drops_low_confidence", [0.9, 0.4], [0.9, 0.5], 1, 1),
            ("keeps_all_confident", [0.8, 0.7], [0.95], 2, 1),
            ("drops_everything", [0.2], [0.1], 0, 0),
        ]
    )
    def test_gate(
        self,
        _name: str,
        section_confs: list[float],
        opp_confs: list[float],
        expect_sections: int,
        expect_opps: int,
    ) -> None:
        out = BriefOut(
            sections=[_section(c) for c in section_confs],
            opportunities=[_opportunity(c) for c in opp_confs],
        )
        gated = apply_say_less_gate(out)
        assert len(gated.sections) == expect_sections
        assert len(gated.opportunities) == expect_opps

    def test_threshold_is_inclusive(self) -> None:
        gated = apply_say_less_gate(BriefOut(sections=[_section(CONFIDENCE_THRESHOLD)], opportunities=[]))
        assert len(gated.sections) == 1

    @patch("products.pulse.backend.generation.synthesize.MaxChatOpenAI")
    async def test_empty_items_short_circuits_without_llm(self, mock_llm: MagicMock) -> None:
        out = await synthesize_brief(team=MagicMock(), user=MagicMock(), config=None, items=[], period_days=7)
        assert out.sections == []
        assert out.opportunities == []
        mock_llm.assert_not_called()
