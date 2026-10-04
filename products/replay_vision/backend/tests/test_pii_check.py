import pytest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from products.replay_vision.backend.error_kinds import FailureKind
from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput

_LEAKY = "(t 12) jane@example.com opened checkout and paid."
_CLEAN = "(t 12) The user opened checkout and paid."


def _output() -> MonitorOutput:
    return MonitorOutput(verdict="yes", reasoning=_LEAKY, confidence=0.9)


async def _check(asks: bool | None, flags: list[bool | None]) -> MonitorOutput:
    with (
        patch.object(pii_check, "asks_for_identity", return_value=asks),
        patch.object(pii_check, "contains_pii", side_effect=flags),
        patch.object(pii_check, "rewrite_without_pii", new=AsyncMock(return_value={"reasoning": _CLEAN})),
    ):
        return await pii_check.keep_unrequested_pii_out(
            _output(), team_id=1, question="did they pay?", scanner_type="monitor", trace_id="t"
        )


@parameterized.expand(
    [
        ("question_asks_for_identity", True, [], _LEAKY),
        ("jev_unavailable", None, [], _LEAKY),
        ("clean_answer", False, [False], _LEAKY),
        ("detector_unavailable", False, [None], _LEAKY),
        ("rewrite_removes_it", False, [True, False], _CLEAN),
    ]
)
@pytest.mark.asyncio
async def test_answer_passes_or_is_rewritten(_name: str, asks: bool | None, flags: list, reasoning: str) -> None:
    result = await _check(asks, flags)
    assert result.reasoning == reasoning
    assert result.verdict == "yes"


@pytest.mark.asyncio
async def test_answer_still_flagged_after_the_rewrite_fails_the_observation() -> None:
    with pytest.raises(ScannerFailureError) as raised:
        await _check(False, [True, True])
    assert raised.value.kind == FailureKind.PII_DETECTED
    assert raised.value.non_retryable
