from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from products.signals.backend.temporal.llm import SAFETY_MODEL
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse, judge_report_safety
from products.signals.backend.temporal.types import SignalData

MODULE_PATH = "products.signals.backend.temporal.report_safety_judge"


@pytest.mark.asyncio
async def test_report_judge_runs_on_the_safety_model() -> None:
    # The judge is the second safety stage, so it must not fall back to the matching model.
    captured: dict[str, str | None] = {}

    async def fake_call_llm(*, model: str | None = None, **_kwargs: object) -> SafetyJudgeResponse:
        captured["model"] = model
        return SafetyJudgeResponse(choice=True)

    signal = SignalData(
        signal_id="signal-1",
        content="a finding",
        source_product="error_tracking",
        source_type="issue_created",
        source_id="issue-1",
        weight=1.0,
        timestamp=datetime(2026, 9, 10, tzinfo=UTC),
    )

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm):
        result = await judge_report_safety(team_id=1, signals=[signal])

    assert result.choice is True
    assert captured["model"] == SAFETY_MODEL
