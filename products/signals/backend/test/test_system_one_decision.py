import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager
from uuid import UUID

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.exceptions import ImproperlyConfigured

from fakeredis import FakeRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.token_bucket import TEST_reset_scripts

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
from products.signals.backend.system_one_decision import (
    JEV_TIMEOUT_SECONDS,
    ModelMode,
    SignalsDecision,
    SignalsDecisionError,
    _query,
    model_mode,
    run_model_decision,
)
from products.signals.backend.system_one_prompts import DEFAULT_SYSTEM_ONE_MODEL, SystemOnePrompt, bundled_prompt
from products.signals.backend.temporal.safety_filter import SafetyFilterJudgeResponse, safety_filter


@pytest.fixture(autouse=True)
def reset_jev_budget() -> Iterator[MagicMock]:
    TEST_reset_scripts()
    with (
        patch("products.signals.backend.system_one_decision.get_client", return_value=FakeRedis()) as get_redis,
        patch("products.signals.backend.system_one_decision.JEV_ADMISSION_TIMEOUT_SECONDS", 600),
        patch("products.signals.backend.system_one_decision.JEV_SHADOW_ADMISSION_TIMEOUT_SECONDS", 600),
    ):
        yield get_redis
    TEST_reset_scripts()


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
    team_id: int = 7,
    stage: str = "actionability",
    traditional: Callable[[str | None], Awaitable[bool]] | None = None,
    system_one_result: Callable[[bool, str | None], bool] | None = None,
    prompt: SystemOnePrompt | None = None,
) -> bool:
    return await run_model_decision(
        team_id=team_id,
        stage=stage,
        primary_model="claude-sonnet-5",
        source_id="issue-1",
        source_product="linear",
        state={"policy_and_record": "policy and issue"},
        prompt=prompt or bundled_prompt("signals-actionability-test", "policy", "Is it actionable?", 0.95),
        traditional=traditional or AsyncMock(return_value=False),
        verdict=lambda value: value,
        system_one_result=system_one_result or (lambda value, _category: value),
    )


@pytest.mark.asyncio
async def test_safety_requests_category_through_the_shared_gateway_client() -> None:
    state: dict[str, JsonValue] = {"signal": "a finding"}
    with patch(
        "products.signals.backend.system_one_decision.decision_api.decide_when_available",
        return_value=_safety_result(),
    ) as decide:
        result = await _query(
            7,
            "signal_safety",
            state,
            bundled_prompt("signals-signal-safety-system-one", "policy", "Is it safe?", 0.9),
            "decision-1",
            "issue-1",
            "linear",
            "system-one-only",
        )

    decide.assert_called_once()
    request = decide.call_args.args[0]
    assert request.team_id == 7
    assert request.model == DEFAULT_SYSTEM_ONE_MODEL
    assert request.ai_product == "signals"
    assert request.trace_id == "decision-1"
    assert request.properties == {
        "signals_decision_id": "decision-1",
        "ai_stage": "signal_safety",
        "source_id": "issue-1",
        "source_product": "linear",
        "$ai_prompt_name": "signals-signal-safety-system-one",
        "system_one_prompt_source": "bundled",
    }
    assert request.state == state
    assert set(request.questions) == {"safe", "category"}
    assert request.questions["safe"].type == DecisionQuestionType.NOUL
    assert request.questions["category"].type == DecisionQuestionType.CHOICE
    assert decide.call_args.kwargs == {"timeout_seconds": JEV_TIMEOUT_SECONDS}
    assert result.category == "secret_exfiltration"
    assert result.category_confidence == 0.88


@pytest.mark.asyncio
async def test_system_one_primary_safety_rejects_a_blocked_category_even_with_a_safe_probability() -> None:
    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_safety_result(probability=0.99),
        ) as decide,
        patch(
            "products.signals.backend.temporal.safety_filter.call_llm",
            new_callable=AsyncMock,
            return_value=SafetyFilterJudgeResponse(safe=True),
        ) as traditional,
    ):
        result = await safety_filter(7, "a finding", source_product="linear", source_id="issue-1")

    assert result.safe is False
    assert result.threat_type == "secret_exfiltration"
    properties = capture.call_args.kwargs["properties"]
    assert properties["category_disagreement"] is True
    assert properties["system_one_category_confidence"] == 0.88
    trace_id = properties["signals_decision_id"]
    assert traditional.await_args is not None
    assert traditional.await_args.kwargs["trace_id"] == trace_id
    assert decide.call_args.args[0].trace_id == trace_id


@pytest.mark.asyncio
async def test_shadow_disagreement_keeps_primary_result_and_records_usage() -> None:
    primary = AsyncMock(return_value=False)
    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="system-one-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_actionability_result(),
        ) as decide,
    ):
        result = await _run_actionability(traditional=primary)

    assert result is False
    properties = capture.call_args.kwargs["properties"]
    assert properties["disagreement"] is True
    assert properties["traditional_verdict"] is False
    assert properties["system_one_verdict"] is True
    assert properties["deciding_provider"] == "traditional"
    assert properties["system_one_input_tokens"] == 1000
    assert properties["system_one_estimated_cost_usd"] == pytest.approx(0.000042)
    trace_id = properties["signals_decision_id"]
    assert UUID(trace_id).version == 4
    assert properties["$ai_trace_id"] == trace_id
    assert primary.await_args is not None
    assert primary.await_args.args == (trace_id,)
    assert decide.call_args.args[0].trace_id == trace_id


@pytest.mark.asyncio
async def test_managed_question_and_threshold_drive_the_decision() -> None:
    prompt = SystemOnePrompt(
        name="signals-actionability-issue",
        policy="policy",
        question="Managed question?",
        model=DEFAULT_SYSTEM_ONE_MODEL,
        threshold=0.91,
        version=2,
        source="managed",
    )
    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="system-one-only",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_actionability_result(probability=0.9),
        ) as decide,
    ):
        result = await _run_actionability(prompt=prompt)

    assert result is False
    request = decide.call_args.args[0]
    assert request.questions["actionable"].instructions == "Managed question?"
    assert request.properties["$ai_prompt_version"] == "2"
    assert capture.call_args.kwargs["properties"]["$ai_prompt_version"] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag_value,expected_mode",
    [("typesafe-shadow", "system-one-shadow"), ("typesafe-only", "system-one-only")],
)
async def test_existing_mode_flag_values_keep_working(flag_value: str, expected_mode: ModelMode) -> None:
    with patch(
        "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag", return_value=flag_value
    ):
        assert await model_mode(7) == expected_mode


@pytest.mark.asyncio
async def test_shadow_budget_is_shared_across_teams_and_stages() -> None:
    with (
        time_machine.travel("2026-01-01", tick=False),
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="system-one-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            side_effect=lambda request, **kwargs: (
                _actionability_result() if "actionable" in request.questions else _safety_result()
            ),
        ) as decide,
    ):
        results = await asyncio.gather(
            *[
                _run_actionability(team_id=team_id, stage=stage)
                for team_id, stage in [(7, "actionability"), (8, "signal_safety"), (9, "report_safety")]
            ]
        )

    assert results == [False, False, False]
    assert decide.call_count == 2
    statuses = [call.kwargs["properties"]["system_one_status"] for call in capture.call_args_list]
    assert sorted(statuses) == ["ok", "ok", "skipped_overload"]
    assert all(call.kwargs["properties"]["deciding_provider"] == "traditional" for call in capture.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["traditional-shadow", "system-one-only"])
async def test_primary_waits_for_budget_refill(mode: ModelMode, reset_jev_budget: MagicMock) -> None:
    with (
        time_machine.travel("2026-01-01", tick=False) as clock,
        patch("products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture"),
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_actionability_result(),
        ) as decide,
        patch(
            "products.signals.backend.system_one_decision.asyncio.sleep", AsyncMock(side_effect=clock.shift)
        ) as sleep,
    ):
        results = [await _run_actionability() for _ in range(3)]

    assert results == [True, True, True]
    assert decide.call_count == 3
    assert all(call.kwargs["timeout_seconds"] == JEV_TIMEOUT_SECONDS for call in decide.call_args_list)
    assert sleep.await_count == 2
    assert all(2 <= call.args[0] <= 2.25 for call in sleep.await_args_list)
    reset_jev_budget.assert_called_with(socket_timeout=0.1, socket_connect_timeout=0.1)


@pytest.mark.asyncio
async def test_busy_team_leaves_capacity_for_another_teams_primary_checks() -> None:
    with (
        time_machine.travel("2026-01-01", tick=False) as clock,
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="system-one-shadow",
        ) as flag,
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture"),
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_actionability_result(),
        ) as decide,
        patch(
            "products.signals.backend.system_one_decision.asyncio.sleep",
            AsyncMock(side_effect=AssertionError("The other team must not wait for capacity")),
        ),
    ):
        for second in range(6):
            flag.return_value = "system-one-shadow"
            await asyncio.gather(*[_run_actionability(team_id=7) for _ in range(20)])
            if second % 2 == 0:
                flag.return_value = "system-one-only"
                assert await _run_actionability(team_id=8) is True
            clock.shift(1)

    teams = [call.args[0].team_id for call in decide.call_args_list]
    assert teams.count(7) == 3
    assert teams.count(8) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["system-one-shadow", "traditional-shadow", "system-one-only"])
@pytest.mark.parametrize("failure", ["redis", "redis_config", "timeout"])
async def test_admission_failure_preserves_mode_semantics(mode: ModelMode, failure: str) -> None:
    traditional = AsyncMock(return_value=False)
    broken_redis = MagicMock()
    broken_redis.register_script.return_value.side_effect = RedisConnectionError("unavailable")
    failure_patch: AbstractContextManager[object]
    if failure == "redis":
        failure_patch = patch("products.signals.backend.system_one_decision.get_client", return_value=broken_redis)
    elif failure == "redis_config":
        failure_patch = patch(
            "products.signals.backend.system_one_decision.get_client", side_effect=ImproperlyConfigured("unconfigured")
        )
    else:
        timeout = (
            "JEV_SHADOW_ADMISSION_TIMEOUT_SECONDS" if mode == "system-one-shadow" else "JEV_ADMISSION_TIMEOUT_SECONDS"
        )
        failure_patch = patch(f"products.signals.backend.system_one_decision.{timeout}", 0)
    with (
        failure_patch,
        patch("products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch("products.signals.backend.system_one_decision.decision_api.decide_when_available") as decide,
    ):
        if mode == "system-one-only":
            with pytest.raises(SignalsDecisionError):
                await _run_actionability(traditional=traditional)
            traditional.assert_not_awaited()
        else:
            assert await _run_actionability(traditional=traditional) is False
            traditional.assert_awaited_once()

    decide.assert_not_called()
    properties = capture.call_args.kwargs["properties"]
    assert properties["system_one_status"] == ("admission_timeout" if failure == "timeout" else "admission_unavailable")
    assert (
        properties["system_one_deciding_provider"]
        == {
            "system-one-shadow": "traditional",
            "traditional-shadow": "traditional_fallback",
            "system-one-only": "system_one",
        }[mode]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,gateway_error,expected_status",
    [("traditional-only", False, None), ("system-one-shadow", True, "RuntimeError")],
)
async def test_disabled_or_failed_shadow_does_not_change_primary_result(
    mode: str, gateway_error: bool, expected_status: str | None
) -> None:
    decide = MagicMock(side_effect=RuntimeError("gateway unavailable") if gateway_error else None)
    with (
        patch("products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch("products.signals.backend.system_one_decision.decision_api.decide_when_available", decide),
    ):
        result = await _run_actionability()

    assert result is False
    if mode == "traditional-only":
        decide.assert_not_called()
        capture.assert_not_called()
    else:
        assert capture.call_args.kwargs["properties"]["system_one_status"] == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_traditional_calls",
    [("traditional-shadow", 1), ("system-one-only", 0)],
)
async def test_system_one_primary_modes(mode: str, expected_traditional_calls: int) -> None:
    traditional = AsyncMock(return_value=False)
    with (
        patch("products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_actionability_result(),
        ),
    ):
        result = await _run_actionability(traditional=traditional)

    assert result is True
    assert traditional.await_count == expected_traditional_calls
    assert capture.call_args.kwargs["properties"]["system_one_deciding_provider"] == "system_one"


@pytest.mark.asyncio
async def test_traditional_shadow_records_the_traditional_comparison() -> None:
    traditional_started = asyncio.Event()
    release_traditional = asyncio.Event()

    async def slow_traditional(_trace_id: str | None) -> bool:
        traditional_started.set()
        await release_traditional.wait()
        return False

    async def system_one_result(*_args: object) -> SignalsDecision:
        await traditional_started.wait()
        release_traditional.set()
        return SignalsDecision(
            probability=0.98,
            model="jevk5-fp8-0.2",
            input_tokens=1000,
            category=None,
            category_confidence=None,
        )

    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision._query", new_callable=AsyncMock, side_effect=system_one_result
        ),
    ):
        result = await asyncio.wait_for(_run_actionability(traditional=slow_traditional), timeout=0.1)

    assert result is True
    properties = capture.call_args.kwargs["properties"]
    assert properties["traditional_status"] == "ok"
    assert properties["traditional_verdict"] is False
    assert properties["disagreement"] is True


@pytest.mark.asyncio
async def test_traditional_shadow_cancels_traditional_when_the_caller_is_cancelled() -> None:
    traditional_started = asyncio.Event()
    traditional_cancelled = asyncio.Event()

    async def slow_traditional(_trace_id: str | None) -> bool:
        traditional_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            traditional_cancelled.set()
            raise
        return False

    async def pending_system_one(*_args: object) -> SignalsDecision:
        await asyncio.Event().wait()
        raise AssertionError("System One call must stay pending")

    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture"),
        patch(
            "products.signals.backend.system_one_decision._query",
            new_callable=AsyncMock,
            side_effect=pending_system_one,
        ),
    ):
        decision = asyncio.create_task(_run_actionability(traditional=slow_traditional))
        await traditional_started.wait()
        decision.cancel()
        with pytest.raises(asyncio.CancelledError):
            await decision

    assert traditional_cancelled.is_set()


@pytest.mark.asyncio
async def test_traditional_shadow_falls_back_when_system_one_fails() -> None:
    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            side_effect=RuntimeError("gateway unavailable"),
        ),
    ):
        result = await _run_actionability()

    assert result is False
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "traditional_fallback"


@pytest.mark.asyncio
async def test_system_one_only_failure_does_not_run_traditional() -> None:
    traditional = AsyncMock(return_value=True)
    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="system-one-only",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture"),
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            side_effect=DecisionGatewayError(422, "echoed signal description"),
        ),
    ):
        with pytest.raises(SignalsDecisionError, match="Signals decision failed") as exc_info:
            await _run_actionability(traditional=traditional)

    assert str(exc_info.value) == "Signals decision failed: DecisionGatewayError (status 422)"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__
    traditional.assert_not_awaited()


@pytest.mark.asyncio
async def test_system_one_only_failure_keeps_actionability_batch() -> None:
    output = SignalEmitterOutput("test", "test", "record-1", "description", 1.0, {})
    with (
        patch("products.signals.backend.emission.pipeline.build_async_anthropic_client"),
        patch(
            "products.signals.backend.emission.pipeline.check_actionability",
            AsyncMock(side_effect=SignalsDecisionError("failed")),
        ),
        patch("products.signals.backend.emission.pipeline.activity"),
    ):
        result = await filter_actionable(MagicMock(id=1), [output], "prompt {description}", extra={})

    assert result == [output]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["system-one-shadow", "traditional-shadow"])
async def test_malformed_system_one_response_keeps_pipeline_running(mode: str) -> None:
    with (
        patch("products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            side_effect=DecisionGatewayError(200, "missing answer"),
        ),
    ):
        result = await _run_actionability()

    assert result is False
    assert capture.call_args.kwargs["properties"]["system_one_status"] == "DecisionGatewayError"


@pytest.mark.asyncio
async def test_system_one_result_conversion_error_falls_back() -> None:
    def invalid_result(_verdict: bool, _category: str | None) -> bool:
        raise ValueError("invalid result")

    with (
        patch(
            "products.signals.backend.system_one_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.system_one_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.system_one_decision.decision_api.decide_when_available",
            return_value=_actionability_result(),
        ),
    ):
        result = await _run_actionability(system_one_result=invalid_result)

    assert result is False
    assert capture.call_args.kwargs["properties"]["system_one_status"] == "ValueError"
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "traditional_fallback"
