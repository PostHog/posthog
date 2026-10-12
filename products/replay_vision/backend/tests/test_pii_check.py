import pytest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from products.replay_vision.backend.error_kinds import FailureKind
from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput

_SUBJECT = "jane@example.com"
_PHONE = "+1 555 0100"
_CLEAN = "(t 12) The user opened checkout and paid."


def _detector(*, team_id: int, text: dict[str, str], trace_id: str) -> bool:
    joined = " ".join(text.values()).lower()
    return _SUBJECT in joined or _PHONE.lower() in joined


async def _check(reasoning: str, asks: bool | None, rewrite_to: str = _CLEAN) -> MonitorOutput:
    with (
        patch.object(pii_check, "asks_for_identity", return_value=asks),
        patch.object(pii_check, "contains_pii", side_effect=_detector),
        patch.object(pii_check, "rewrite_without_pii", new=AsyncMock(return_value={"reasoning": rewrite_to})),
    ):
        return await pii_check.keep_unrequested_pii_out(
            MonitorOutput(verdict="yes", reasoning=reasoning, confidence=0.9),
            team_id=1,
            question="Who is this user?",
            identity_values=["Jane@Example.com", "Jane Doe"],
            scanner_type="monitor",
            trace_id="t",
        )


@parameterized.expand(
    [
        ("clean_answer", _CLEAN, False, _CLEAN),
        ("jev_unavailable", f"(t 12) {_SUBJECT} paid.", None, f"(t 12) {_SUBJECT} paid."),
        ("unasked_identity_is_rewritten", f"(t 12) {_SUBJECT} paid.", False, _CLEAN),
        ("asked_identity_stays", f"(t 12) {_SUBJECT} paid.", True, f"(t 12) {_SUBJECT} paid."),
        # The question allows the subject's identity, not every personal detail around it.
        ("other_data_next_to_asked_identity_is_rewritten", f"(t 12) {_SUBJECT} called {_PHONE}.", True, _CLEAN),
    ]
)
@pytest.mark.asyncio
async def test_answer_passes_or_is_rewritten(_name: str, reasoning: str, asks: bool | None, expected: str) -> None:
    result = await _check(reasoning, asks)
    assert result.reasoning == expected
    assert result.verdict == "yes"


@pytest.mark.asyncio
async def test_answer_still_flagged_after_the_rewrite_fails_the_observation() -> None:
    with pytest.raises(ScannerFailureError) as raised:
        await _check(f"(t 12) {_SUBJECT} paid.", False, rewrite_to=f"(t 12) {_SUBJECT} paid, again.")
    assert raised.value.kind == FailureKind.PII_DETECTED
    assert raised.value.non_retryable
