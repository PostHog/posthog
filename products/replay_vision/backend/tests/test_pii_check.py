import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.pii_check import PiiCheckContext, has_unrequested_pii
from products.replay_vision.backend.temporal.scanners.monitor import MonitorLlmResponse

_CTX = PiiCheckContext(team_id=1, question="Did the user pay?", scanner_type="monitor", trace_id="t")


def _answer() -> MonitorLlmResponse:
    return MonitorLlmResponse.model_validate(
        {"verdict": "yes", "reasoning": "(t 12) jane@example.com paid.", "confidence": 0.9, "notability": 0.2}
    )


@parameterized.expand(
    [
        ("personal_data_unasked", 0.05, 0.95, True),
        ("clean_answer", 0.05, 0.1, False),
        ("question_asks_for_identity", 0.9, 0.95, False),
        ("jev_cannot_judge_the_question", None, 0.95, False),
        ("jev_cannot_judge_the_answer", 0.05, None, False),
    ]
)
@pytest.mark.asyncio
async def test_flags_only_personal_data_the_question_did_not_ask_for(
    _name: str, asks: float | None, detected: float | None, flagged: bool
) -> None:
    def fake(ctx: PiiCheckContext, state: dict, instructions: str) -> float | None:
        return asks if instructions == pii_check._ASKS_QUESTION else detected

    with patch.object(pii_check, "_yes_probability", side_effect=fake):
        assert await has_unrequested_pii(_answer(), _CTX) is flagged
