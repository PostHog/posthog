import asyncio
from collections.abc import Awaitable, Callable

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionResult,
    JsonValue,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.signals.backend.emission.pipeline import filter_actionable
from products.signals.backend.emission.registry import SignalEmitterOutput
from products.signals.backend.temporal.safety_filter import SafetyFilterJudgeResponse, safety_filter
from products.signals.backend.typesafe_decision import (
    JEV_MODEL,
    JEV_TIMEOUT_SECONDS,
    SignalsDecision,
    SignalsDecisionError,
    _query,
    run_model_decision,
)


def _actionability_result(probability: float = 0.98) -> DecisionResult:
    return DecisionResult(
        model="jevk5-fp8-0.2",
        answers={"actionable": NoulAnswer(probability=probability)},
        input_tokens=1000,
    )


def _safety_result(probability: float = 0.2) -> DecisionResult:
    return DecisionResult(
        model="jevk5-fp8-0.2",
        answers={
            "safe": NoulAnswer(probability=probability),
            "category": ChoiceAnswer(
                choice="secret_exfiltration",
                confidence=0.88,
                probabilities={"secret_exfiltration": 0.88, "none": 0.12},
            ),
        },
        input_tokens=1100,
    )


async def _run_actionability(
    *,
    traditional: Callable[[], Awaitable[bool]] | None = None,
    typesafe_result: Callable[[bool, str | None], bool] | None = None,
) -> bool:
    return await run_model_decision(
        team_id=7,
        stage="actionability",
        primary_model="claude-sonnet-5",
        source_id="issue-1",
        source_product="linear",
        state={"policy_and_record": "policy and issue"},
        instructions="Is it actionable?",
        threshold=0.95,
        traditional=traditional or AsyncMock(return_value=False),
        verdict=lambda value: value,
        typesafe_result=typesafe_result or (lambda value, _category: value),
    )


@pytest.mark.asyncio
async def test_safety_requests_category_through_the_shared_gateway_client() -> None:
    state: dict[str, JsonValue] = {"signal": "a finding"}
    with patch(
        "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
        return_value=_safety_result(),
    ) as decide:
        result = await _query(7, "signal_safety", state, "Is it safe?")

    decide.assert_called_once()
    request = decide.call_args.args[0]
    assert request.team_id == 7
    assert request.model == JEV_MODEL
    assert request.ai_product == "signals"
    assert request.state == state
    assert set(request.questions) == {"safe", "category"}
    assert request.questions["safe"].type == DecisionQuestionType.NOUL
    assert request.questions["category"].type == DecisionQuestionType.CHOICE
    assert decide.call_args.kwargs == {"timeout_seconds": JEV_TIMEOUT_SECONDS}
    assert result.category == "secret_exfiltration"
    assert result.category_confidence == 0.88


@pytest.mark.asyncio
async def test_typesafe_primary_safety_rejects_a_blocked_category_even_with_a_safe_probability() -> None:
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            return_value=_safety_result(probability=0.99),
        ),
        patch(
            "products.signals.backend.temporal.safety_filter.call_llm",
            new_callable=AsyncMock,
            return_value=SafetyFilterJudgeResponse(safe=True),
        ),
    ):
        result = await safety_filter(7, "a finding", source_product="linear", source_id="issue-1")

    assert result.safe is False
    assert result.threat_type == "secret_exfiltration"
    properties = capture.call_args.kwargs["properties"]
    assert properties["category_disagreement"] is True
    assert properties["typesafe_category_confidence"] == 0.88


@pytest.mark.asyncio
async def test_shadow_disagreement_keeps_primary_result_and_records_usage() -> None:
    primary = AsyncMock(return_value=False)
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="typesafe-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            return_value=_actionability_result(),
        ),
    ):
        result = await _run_actionability(traditional=primary)

    assert result is False
    properties = capture.call_args.kwargs["properties"]
    assert properties["disagreement"] is True
    assert properties["traditional_verdict"] is False
    assert properties["typesafe_verdict"] is True
    assert properties["deciding_provider"] == "traditional"
    assert properties["typesafe_input_tokens"] == 1000
    assert properties["typesafe_estimated_cost_usd"] == pytest.approx(0.000042)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,gateway_error,expected_status",
    [("traditional-only", False, None), ("typesafe-shadow", True, "RuntimeError")],
)
async def test_disabled_or_failed_shadow_does_not_change_primary_result(
    mode: str, gateway_error: bool, expected_status: str | None
) -> None:
    decide = MagicMock(side_effect=RuntimeError("gateway unavailable") if gateway_error else None)
    with (
        patch("products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch("products.signals.backend.typesafe_decision.decision_api.decide_unchecked", decide),
    ):
        result = await _run_actionability()

    assert result is False
    if mode == "traditional-only":
        decide.assert_not_called()
        capture.assert_not_called()
    else:
        assert capture.call_args.kwargs["properties"]["typesafe_status"] == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_traditional_calls",
    [("traditional-shadow", 1), ("typesafe-only", 0)],
)
async def test_typesafe_primary_modes(mode: str, expected_traditional_calls: int) -> None:
    traditional = AsyncMock(return_value=False)
    with (
        patch("products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            return_value=_actionability_result(),
        ),
    ):
        result = await _run_actionability(traditional=traditional)

    assert result is True
    assert traditional.await_count == expected_traditional_calls
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "typesafe"


@pytest.mark.asyncio
async def test_traditional_shadow_returns_without_waiting_for_traditional() -> None:
    traditional_started = asyncio.Event()
    traditional_cancelled = asyncio.Event()

    async def slow_traditional() -> bool:
        traditional_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            traditional_cancelled.set()
            raise
        return False

    async def typesafe_result(*_args: object) -> SignalsDecision:
        await traditional_started.wait()
        return SignalsDecision(
            probability=0.98,
            model="jevk5-fp8-0.2",
            input_tokens=1000,
            category=None,
            category_confidence=None,
        )

    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch("products.signals.backend.typesafe_decision._query", new_callable=AsyncMock, side_effect=typesafe_result),
    ):
        result = await asyncio.wait_for(
            _run_actionability(traditional=slow_traditional),
            timeout=0.1,
        )

    assert result is True
    assert traditional_cancelled.is_set()
    assert capture.call_args.kwargs["properties"]["traditional_status"] == "cancelled"


@pytest.mark.asyncio
async def test_traditional_shadow_falls_back_when_typesafe_fails() -> None:
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            side_effect=RuntimeError("gateway unavailable"),
        ),
    ):
        result = await _run_actionability()

    assert result is False
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "traditional_fallback"


@pytest.mark.asyncio
async def test_typesafe_only_failure_does_not_run_traditional() -> None:
    traditional = AsyncMock(return_value=True)
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="typesafe-only",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture"),
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            side_effect=RuntimeError("gateway unavailable"),
        ),
    ):
        with pytest.raises(SignalsDecisionError, match="Signals decision failed") as exc_info:
            await _run_actionability(traditional=traditional)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    traditional.assert_not_awaited()


@pytest.mark.asyncio
async def test_typesafe_only_failure_stops_actionability_batch() -> None:
    output = SignalEmitterOutput("test", "test", "record-1", "description", 1.0, {})
    with (
        patch("products.signals.backend.emission.pipeline.build_async_anthropic_client"),
        patch(
            "products.signals.backend.emission.pipeline.check_actionability",
            AsyncMock(side_effect=SignalsDecisionError("failed")),
        ),
        patch("products.signals.backend.emission.pipeline.activity"),
    ):
        with pytest.raises(ExceptionGroup) as exc_info:
            await filter_actionable(MagicMock(id=1), [output], "prompt {description}", extra={})

    assert any(isinstance(error, SignalsDecisionError) for error in exc_info.value.exceptions)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["typesafe-shadow", "traditional-shadow"])
async def test_malformed_typesafe_response_keeps_pipeline_running(mode: str) -> None:
    with (
        patch("products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            side_effect=DecisionGatewayError(200, "missing answer"),
        ),
    ):
        result = await _run_actionability()

    assert result is False
    assert capture.call_args.kwargs["properties"]["typesafe_status"] == "DecisionGatewayError"


@pytest.mark.asyncio
async def test_typesafe_result_conversion_error_falls_back() -> None:
    def invalid_result(_verdict: bool, _category: str | None) -> bool:
        raise ValueError("invalid result")

    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.decision_api.decide_unchecked",
            return_value=_actionability_result(),
        ),
    ):
        result = await _run_actionability(typesafe_result=invalid_result)

    assert result is False
    assert capture.call_args.kwargs["properties"]["typesafe_status"] == "ValueError"
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "traditional_fallback"
