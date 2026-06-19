import json

import pytest
from unittest.mock import AsyncMock, patch

from products.signals.backend.temporal.dreaming.briefing import (
    BRIEFING_ITEM_COUNT,
    BriefingContext,
    build_briefing_prompt,
    coerce_to_three_items,
    generate_briefing,
)


def _context(dismissal_notes: tuple[str, ...] = ()) -> BriefingContext:
    return BriefingContext(
        project_name="Acme",
        scout_skills=("signals-scout-error-tracking", "signals-scout-experiments"),
        recent_report_titles=("Checkout funnel dropped 12%", "New error spike in payments"),
        profile_highlights=("Product analytics + error tracking in use", "3 active experiments"),
        dismissal_notes=dismissal_notes,
    )


def _item(n: int) -> dict:
    return {"headline": f"Headline {n}", "detail": f"Detail {n}"}


class TestBriefingContract:
    @pytest.mark.parametrize(
        "raw_items",
        [
            [],
            [_item(1)],
            [_item(1), _item(2)],
            [_item(1), _item(2), _item(3)],
            [_item(1), _item(2), _item(3), _item(4), _item(5)],
        ],
    )
    def test_always_exactly_three_items(self, raw_items):
        items = coerce_to_three_items(raw_items, _context())
        assert len(items) == BRIEFING_ITEM_COUNT

    def test_malformed_entries_dropped_then_topped_up(self):
        raw = [{"headline": "good", "detail": "ok"}, "not a dict", {"detail": "no headline"}, {"headline": ""}]
        items = coerce_to_three_items(raw, _context())
        assert len(items) == BRIEFING_ITEM_COUNT
        assert items[0].headline == "good"

    def test_long_fields_are_clipped(self):
        raw = [{"headline": "h" * 500, "detail": "d" * 5000}]
        items = coerce_to_three_items(raw, _context())
        assert len(items[0].headline) <= 121  # cap + ellipsis
        assert len(items[0].detail) <= 401

    def test_prompt_includes_context(self):
        prompt = build_briefing_prompt(_context())
        assert "Acme" in prompt
        assert "signals-scout-error-tracking" in prompt
        assert "Checkout funnel dropped 12%" in prompt

    def test_prompt_with_empty_context_still_valid(self):
        ctx = BriefingContext("Empty", (), (), ())
        prompt = build_briefing_prompt(ctx)
        assert "Empty" in prompt
        assert "Exactly 3" in prompt

    def test_prompt_includes_dismissal_notes(self):
        prompt = build_briefing_prompt(
            _context(dismissal_notes=("12 report(s) dismissed.", "By reason: not_a_bug (9)."))
        )
        assert "not_a_bug (9)" in prompt
        assert "mass-dismissed" in prompt

    def test_prompt_omits_dismissal_section_when_empty(self):
        prompt = build_briefing_prompt(_context())
        assert "dismissed" not in prompt

    def test_dismissals_preserve_exactly_three_contract(self):
        # Even with a dismissal-driven fallback in play, the contract holds.
        items = coerce_to_three_items([], _context(dismissal_notes=("8 report(s) dismissed.",)))
        assert len(items) == BRIEFING_ITEM_COUNT
        assert any("dismiss" in item.headline.lower() for item in items)


class TestGenerateBriefing:
    @pytest.mark.asyncio
    async def test_generate_uses_llm_result(self):
        valid = json.dumps({"intro": "here we go", "items": [_item(1), _item(2), _item(3)]})

        async def fake_call_llm(*, validate, **kwargs):
            return validate(valid)

        with patch(
            "products.signals.backend.temporal.llm.call_llm",
            new=AsyncMock(side_effect=fake_call_llm),
        ):
            briefing = await generate_briefing(team_id=1, context=_context())

        assert briefing.intro == "here we go"
        assert len(briefing.items) == BRIEFING_ITEM_COUNT

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_llm_error(self):
        with patch(
            "products.signals.backend.temporal.llm.call_llm",
            new=AsyncMock(side_effect=RuntimeError("model down")),
        ):
            briefing = await generate_briefing(team_id=1, context=_context())

        # Fallback still honors the exactly-three contract and is context-aware.
        assert len(briefing.items) == BRIEFING_ITEM_COUNT
        assert briefing.intro
