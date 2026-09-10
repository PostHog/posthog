from collections.abc import Callable

import pytest
from freezegun import freeze_time
from unittest.mock import patch

from products.signals.backend.temporal.llm import SAFETY_MODEL
from products.signals.backend.temporal.safety_filter import (
    SAFETY_FILTER_PROMPT,
    SafetyFilterJudgeResponse,
    safety_filter,
)

MODULE_PATH = "products.signals.backend.temporal.safety_filter"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_product,source_type,expected_source",
    [
        ("signals_scout", "cross_source_issue", "signals_scout / cross_source_issue"),
        ("error_tracking", "issue_created", "error_tracking / issue_created"),
        ("github", None, "github"),
        (None, None, "unknown"),
    ],
)
async def test_safety_filter_wires_prompt_source_and_model(
    source_product: str | None, source_type: str | None, expected_source: str
) -> None:
    # Guards the single prompt for every source, the source and date preamble, and SAFETY_MODEL wiring.
    captured: dict[str, str] = {}

    async def fake_call_llm(
        *,
        team_id: int | None,
        system_prompt: str,
        user_prompt: str,
        validate: Callable[[str], SafetyFilterJudgeResponse],
        stage: str,
        ai_product: str,
        model: str,
        **_kwargs: object,
    ) -> SafetyFilterJudgeResponse:
        captured.update(system_prompt=system_prompt, user_prompt=user_prompt, ai_product=ai_product, model=model)
        return SafetyFilterJudgeResponse(safe=True)

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm), freeze_time("2026-09-10"):
        result = await safety_filter(1, "a finding", source_product=source_product, source_type=source_type)

    assert result.safe is True
    assert captured["system_prompt"] == SAFETY_FILTER_PROMPT
    assert captured["model"] == SAFETY_MODEL
    assert captured["ai_product"] == "signals_safety"
    assert f"Source: {expected_source}" in captured["user_prompt"]
    assert "Current date: 2026-09-10" in captured["user_prompt"]
    assert "a finding" in captured["user_prompt"]
