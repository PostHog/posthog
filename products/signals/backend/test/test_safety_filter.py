import pytest
from unittest.mock import patch

from products.signals.backend.temporal.safety_filter import (
    SAFETY_FILTER_PROMPT,
    SCOUT_SAFETY_FILTER_PROMPT,
    SafetyFilterJudgeResponse,
    safety_filter,
)

MODULE_PATH = "products.signals.backend.temporal.safety_filter"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_product,expected_prompt",
    [
        ("signals_scout", SCOUT_SAFETY_FILTER_PROMPT),
        ("error_tracking", SAFETY_FILTER_PROMPT),
        ("llm_analytics", SAFETY_FILTER_PROMPT),
        ("zendesk", SAFETY_FILTER_PROMPT),
        (None, SAFETY_FILTER_PROMPT),
    ],
)
async def test_safety_filter_selects_prompt_by_source(source_product, expected_prompt):
    captured: dict[str, str] = {}

    async def fake_call_llm(*, team_id, system_prompt, user_prompt, validate, stage):
        captured["system_prompt"] = system_prompt
        return SafetyFilterJudgeResponse(safe=True)

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm):
        result = await safety_filter(1, "a finding", source_product=source_product)

    assert result.safe is True
    assert captured["system_prompt"] == expected_prompt


@pytest.mark.asyncio
async def test_scout_prompt_differs_from_default():
    """Guard against the two prompts drifting back into one — the scout variant must stay distinct."""
    assert SCOUT_SAFETY_FILTER_PROMPT != SAFETY_FILTER_PROMPT
    assert "first-party" in SCOUT_SAFETY_FILTER_PROMPT.lower()
