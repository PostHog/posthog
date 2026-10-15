from typing import Any

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


async def _rewrite_with(side_effect: list[Any]) -> tuple[MonitorOutput, AsyncMock, AsyncMock]:
    rewrite = AsyncMock(side_effect=side_effect)
    sleep = AsyncMock()
    with (
        patch.object(pii_check, "asks_for_identity", return_value=False),
        patch.object(pii_check, "contains_pii", side_effect=_detector),
        patch.object(pii_check, "rewrite_without_pii", new=rewrite),
        patch.object(pii_check.asyncio, "sleep", new=sleep),
    ):
        out = await pii_check.keep_unrequested_pii_out(
            MonitorOutput(verdict="yes", reasoning=f"(t 12) {_SUBJECT} paid.", confidence=0.9),
            team_id=1,
            question="What happened?",
            identity_values=[],
            scanner_type="monitor",
            trace_id="t",
        )
    return out, rewrite, sleep


@parameterized.expand([("rate_limited", 429), ("unavailable", 503)])
@pytest.mark.asyncio
async def test_a_transient_rewrite_failure_retries_the_rewrite_in_place(_name: str, code: int) -> None:
    from google.genai import errors as genai_errors

    error = genai_errors.APIError(code, {"error": {"code": code}})
    out, rewrite, sleep = await _rewrite_with([error, {"reasoning": _CLEAN}])
    assert out.reasoning == _CLEAN
    assert rewrite.await_count == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_rewrite_that_stays_transient_reaches_the_activity_retry() -> None:
    from google.genai import errors as genai_errors

    error = genai_errors.APIError(429, {"error": {"code": 429}})
    with pytest.raises(genai_errors.APIError) as raised:
        await _rewrite_with([error, error, error])
    assert raised.value.code == 429


@pytest.mark.asyncio
async def test_a_rejected_rewrite_still_fails_as_pii_detected() -> None:
    from google.genai import errors as genai_errors

    rewrite = AsyncMock(side_effect=genai_errors.APIError(400, {"error": {"code": 400}}))
    with (
        patch.object(pii_check, "asks_for_identity", return_value=False),
        patch.object(pii_check, "contains_pii", side_effect=_detector),
        patch.object(pii_check, "rewrite_without_pii", new=rewrite),
        pytest.raises(ScannerFailureError) as raised,
    ):
        await pii_check.keep_unrequested_pii_out(
            MonitorOutput(verdict="yes", reasoning=f"(t 12) {_SUBJECT} paid.", confidence=0.9),
            team_id=1,
            question="What happened?",
            identity_values=[],
            scanner_type="monitor",
            trace_id="t",
        )
    assert raised.value.kind == FailureKind.PII_DETECTED
    assert rewrite.await_count == 1
