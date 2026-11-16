import pytest
from unittest.mock import AsyncMock, patch

from google.genai import errors as genai_errors
from parameterized import parameterized

from products.ml_inference.backend.facade.contracts import DecisionGatewayError, DecisionResult, NoulAnswer
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


async def _check(
    reasoning: str, asks: bool | None, rewrite_to: str = _CLEAN, rewrite_error: Exception | None = None
) -> MonitorOutput:
    rewrite = AsyncMock(return_value={"reasoning": rewrite_to}, side_effect=rewrite_error)
    with (
        patch.object(pii_check, "asks_for_identity", return_value=asks),
        patch.object(pii_check, "contains_pii", side_effect=_detector),
        patch.object(pii_check, "rewrite_without_pii", new=rewrite),
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


def _refusal(domain: str, code: int = 402) -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"code": code, "details": [{"domain": domain}]}})


@pytest.mark.parametrize("code", [402, 404, 429])
@pytest.mark.asyncio
async def test_a_gateway_refusal_of_the_rewrite_reaches_the_activity_boundary(code: int) -> None:
    refusal = _refusal("posthog.com", code)
    with pytest.raises(genai_errors.ClientError) as raised:
        await _check(f"(t 12) {_SUBJECT} paid.", False, rewrite_error=refusal)
    assert raised.value is refusal


@pytest.mark.asyncio
async def test_a_provider_refusal_of_the_rewrite_fails_the_observation() -> None:
    with pytest.raises(ScannerFailureError) as raised:
        await _check(f"(t 12) {_SUBJECT} paid.", False, rewrite_error=_refusal("googleapis.com"))
    assert raised.value.kind == FailureKind.PII_DETECTED


@parameterized.expand(
    [
        ("name_only", 0.9, 0.1, True),
        ("contact_only", 0.1, 0.9, True),
        ("neither", 0.1, 0.1, False),
        ("both_just_below_the_bar", 0.39, 0.39, False),
    ]
)
def test_contains_pii_flags_when_either_question_clears_the_bar(
    _name: str, name: float, contact: float, expected: bool
) -> None:
    result = DecisionResult(
        model=pii_check.PII_CHECK_MODEL,
        answers={"name": NoulAnswer(probability=name), "contact": NoulAnswer(probability=contact)},
        input_tokens=1,
    )
    with (
        patch.object(pii_check.decision_api, "decisions_available_here", return_value=True),
        patch.object(pii_check.decision_api, "decide_when_available", return_value=result),
    ):
        assert pii_check.contains_pii(team_id=1, text={"reasoning": _CLEAN}, trace_id="t") is expected


def test_contains_pii_is_unknown_when_the_gateway_fails() -> None:
    with (
        patch.object(pii_check.decision_api, "decisions_available_here", return_value=True),
        patch.object(pii_check.decision_api, "decide_when_available", side_effect=DecisionGatewayError(503, "busy")),
    ):
        assert pii_check.contains_pii(team_id=1, text={"reasoning": _CLEAN}, trace_id="t") is None
