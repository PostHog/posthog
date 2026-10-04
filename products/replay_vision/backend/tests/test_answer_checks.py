import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.replay_vision.backend.temporal import answer_checks
from products.replay_vision.backend.temporal.answer_checks import (
    CONCLUSION,
    FORMAT,
    GROUNDED,
    ON_QUESTION,
    PII,
    CheckContext,
    check_answer,
)
from products.replay_vision.backend.temporal.scanners.monitor import MonitorLlmResponse

_CTX = CheckContext(
    team_id=1,
    question="Did the user pay?",
    scanner_type="monitor",
    trace_id="t",
    events=[{"vid_t": 12, "event": "$pageview", "$current_url": "https://example.com/checkout"}],
)


def _answer() -> MonitorLlmResponse:
    return MonitorLlmResponse.model_validate(
        {
            "verdict": "yes",
            "reasoning": "(t 12) The user opened checkout and paid.",
            "confidence": 0.9,
            "notability": 0.2,
        }
    )


def _probabilities(by_check: dict[str, float | None], asks: float = 0.05):
    instructions = {check.instructions: check.name for check in answer_checks._CHECKS}

    def fake(ctx: CheckContext, state: dict, instructions_text: str) -> float | None:
        if instructions_text == answer_checks._ASKS_FOR_IDENTITY:
            return asks
        return by_check.get(instructions[instructions_text])

    return patch.object(answer_checks, "_yes_probability", side_effect=fake)


_ALL = (PII, CONCLUSION, GROUNDED, FORMAT, ON_QUESTION)


@parameterized.expand(
    [
        ("all_pass", {PII: 0.1, CONCLUSION: 0.9, GROUNDED: 0.1, FORMAT: 0.9, ON_QUESTION: 0.9}, []),
        ("personal_data", {PII: 0.9, CONCLUSION: 0.9, GROUNDED: 0.1, FORMAT: 0.9, ON_QUESTION: 0.9}, [PII]),
        (
            "contradicted_by_events",
            {PII: 0.1, CONCLUSION: 0.9, GROUNDED: 0.9, FORMAT: 0.9, ON_QUESTION: 0.9},
            [GROUNDED],
        ),
        (
            "unsupported_and_off_question",
            {PII: 0.1, CONCLUSION: 0.05, GROUNDED: 0.1, FORMAT: 0.9, ON_QUESTION: 0.05},
            [CONCLUSION, ON_QUESTION],
        ),
        ("ignores_format", {PII: 0.1, CONCLUSION: 0.9, GROUNDED: 0.1, FORMAT: 0.05, ON_QUESTION: 0.9}, [FORMAT]),
        ("jev_cannot_answer", {}, []),
    ]
)
@pytest.mark.asyncio
async def test_each_check_fails_only_on_its_own_signal(_name: str, probabilities: dict, failed: list[str]) -> None:
    with _probabilities(probabilities):
        failures = await check_answer(_answer(), _CTX, checks=_ALL)
    assert sorted(f.check for f in failures) == sorted(failed)


@pytest.mark.asyncio
async def test_a_question_that_asks_for_identity_skips_the_personal_data_check() -> None:
    with _probabilities({PII: 0.95}, asks=0.9):
        assert await check_answer(_answer(), _CTX, checks=(PII,)) == []
