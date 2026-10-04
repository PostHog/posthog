import pytest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from products.replay_vision.backend.error_kinds import FailureKind
from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.scanners.base import SignalFinding
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput

_LEAKY = "(t 12) jane@example.com opened checkout and paid."
_CLEAN = "(t 12) The user opened checkout and paid."
_LEAKY_SIGNAL = "Jane Doe's saved card failed to load on the payment step."
_CLEAN_SIGNAL = "The user's saved card failed to load on the payment step."


def _signal(description: str) -> SignalFinding:
    return SignalFinding(
        problem_type="bug",
        headline="Saved card fails to load",
        description=description,
        confidence=0.8,
        start_time=10,
        end_time=20,
        url="https://example.com/checkout",
    )


async def _check(
    asks: bool | None, flags: list[bool | None], rewrite: dict[str, str]
) -> tuple[MonitorOutput, list[SignalFinding]]:
    with (
        patch.object(pii_check, "asks_for_identity", return_value=asks),
        patch.object(pii_check, "contains_pii", side_effect=flags),
        patch.object(pii_check, "rewrite_without_pii", new=AsyncMock(return_value=rewrite)),
    ):
        return await pii_check.keep_unrequested_pii_out(
            MonitorOutput(verdict="yes", reasoning=_LEAKY, confidence=0.9),
            [_signal(_LEAKY_SIGNAL)],
            team_id=1,
            question="did they pay?",
            scanner_type="monitor",
            trace_id="t",
        )


@parameterized.expand(
    [
        ("question_asks_for_identity", True, [], {}, _LEAKY, _LEAKY_SIGNAL),
        ("jev_unavailable", None, [], {}, _LEAKY, _LEAKY_SIGNAL),
        ("clean_answer", False, [False], {}, _LEAKY, _LEAKY_SIGNAL),
        ("detector_unavailable", False, [None], {}, _LEAKY, _LEAKY_SIGNAL),
        ("rewrite_removes_it", False, [True, False], {"reasoning": _CLEAN}, _CLEAN, _LEAKY_SIGNAL),
        (
            "rewrite_reaches_a_signal",
            False,
            [True, False],
            {"signal_0_description": _CLEAN_SIGNAL},
            _LEAKY,
            _CLEAN_SIGNAL,
        ),
    ]
)
@pytest.mark.asyncio
async def test_answer_and_signals_pass_or_are_rewritten(
    _name: str, asks: bool | None, flags: list, rewrite: dict[str, str], reasoning: str, description: str
) -> None:
    answer, signals = await _check(asks, flags, rewrite)
    assert answer.reasoning == reasoning
    assert answer.verdict == "yes"
    assert [s.description for s in signals] == [description]


@pytest.mark.asyncio
async def test_text_still_flagged_after_the_rewrite_fails_the_observation() -> None:
    with pytest.raises(ScannerFailureError) as raised:
        await _check(False, [True, True], {"reasoning": _CLEAN})
    assert raised.value.kind == FailureKind.PII_DETECTED
    assert raised.value.non_retryable


def test_signal_text_is_part_of_what_jev_reads() -> None:
    text = pii_check.answer_text(
        MonitorOutput(verdict="yes", reasoning=_CLEAN, confidence=0.9), [_signal(_LEAKY_SIGNAL)]
    )
    assert text["signal_0_description"] == _LEAKY_SIGNAL
    assert text["signal_0_headline"] == "Saved card fails to load"
