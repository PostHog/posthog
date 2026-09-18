import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from products.signals.backend.emission.pipeline import filter_actionable
from products.signals.backend.emission.registry import SignalEmitterOutput
from products.signals.backend.temporal.safety_filter import SafetyFilterJudgeResponse, safety_filter
from products.signals.backend.typesafe_decision import TypesafeDecisionError, _query, run_model_decision


class _CloudflareResponse:
    status = 200

    async def __aenter__(self) -> "_CloudflareResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    async def json(self) -> dict[str, object]:
        return {
            "model": "jev-1.13.0",
            "answers": {"actionable": {"type": "noul", "noul": 0.98}},
            "usage": {"input_tokens": 1000, "output_tokens": 20},
        }


class _CloudflareSafetyResponse(_CloudflareResponse):
    async def json(self) -> dict[str, object]:
        return {
            "model": "jev-1.13.0",
            "answers": {
                "safe": {"type": "noul", "noul": 0.2},
                "category": {"type": "choice", "choice": "secret_exfiltration", "confidence": 0.88},
            },
            "usage": {"input_tokens": 1100, "output_tokens": 30},
        }


class _MalformedCloudflareResponse(_CloudflareResponse):
    async def json(self) -> dict[str, object]:
        return {"model": "jev-1.13.0", "answers": {}}


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
async def test_safety_requests_category_in_same_call() -> None:
    with patch(
        "products.signals.backend.typesafe_decision.cloudflare_ai_request",
        new_callable=AsyncMock,
        return_value=_CloudflareSafetyResponse(),
    ) as request:
        result = await _query("signal_safety", {"signal": "a finding"}, "Is it safe?")

    assert request.await_count == 1
    assert request.await_args is not None
    questions = request.await_args.kwargs["payload"]["input"]["questions"]
    assert set(questions) == {"safe", "category"}
    assert questions["category"]["type"] == "choice"
    assert result["category"] == "secret_exfiltration"
    assert result["category_confidence"] == 0.88


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
async def test_typesafe_primary_safety_preserves_category() -> None:
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            return_value=_CloudflareSafetyResponse(),
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
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
async def test_shadow_disagreement_keeps_primary_result_and_records_usage() -> None:
    primary = AsyncMock(return_value=False)
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="typesafe-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            return_value=_CloudflareResponse(),
        ) as request,
    ):
        result = await run_model_decision(
            team_id=7,
            stage="actionability",
            primary_model="claude-sonnet-5",
            source_id="issue-1",
            source_product="linear",
            state={"policy_and_record": "policy and issue"},
            instructions="Is it actionable?",
            threshold=0.95,
            traditional=primary,
            verdict=lambda value: value,
            typesafe_result=lambda value, _category: value,
        )

    assert result is False
    assert request.await_args is not None
    assert request.await_args.kwargs["payload"]["model"] == "typesafe/jev"
    assert request.await_args.kwargs["payload"]["input"]["questions"]["actionable"]["type"] == "noul"
    properties = capture.call_args.kwargs["properties"]
    assert properties["disagreement"] is True
    assert properties["traditional_verdict"] is False
    assert properties["typesafe_verdict"] is True
    assert properties["deciding_provider"] == "traditional"
    assert properties["typesafe_input_tokens"] == 1000
    assert properties["typesafe_direct_list_cost_usd"] == pytest.approx(0.000042)


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
@pytest.mark.parametrize(
    "mode,cloudflare_error,expected_status",
    [("traditional-only", False, None), ("typesafe-shadow", True, "RuntimeError")],
)
async def test_disabled_or_failed_shadow_does_not_change_primary_result(
    mode: str, cloudflare_error: bool, expected_status: str | None
) -> None:
    request = AsyncMock(side_effect=RuntimeError("Cloudflare unavailable") if cloudflare_error else None)
    with (
        patch("products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch("products.signals.backend.typesafe_decision.cloudflare_ai_request", request),
    ):
        result = await run_model_decision(
            team_id=7,
            stage="actionability",
            primary_model="claude-sonnet-5",
            source_id="issue-1",
            source_product="linear",
            state={"policy_and_record": "policy and issue"},
            instructions="Is it actionable?",
            threshold=0.95,
            traditional=AsyncMock(return_value=False),
            verdict=lambda value: value,
            typesafe_result=lambda value, _category: value,
        )

    assert result is False
    if mode != "traditional-only":
        assert capture.call_args.kwargs["properties"]["typesafe_status"] == expected_status
    else:
        request.assert_not_awaited()
        capture.assert_not_called()


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
@pytest.mark.parametrize(
    "mode,expected_traditional_calls,expected_decider",
    [("traditional-shadow", 1, "typesafe"), ("typesafe-only", 0, "typesafe")],
)
async def test_typesafe_primary_modes(mode: str, expected_traditional_calls: int, expected_decider: str) -> None:
    traditional = AsyncMock(return_value=False)
    with (
        patch("products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            return_value=_CloudflareResponse(),
        ),
    ):
        result = await run_model_decision(
            team_id=7,
            stage="actionability",
            primary_model="claude-sonnet-5",
            source_id="issue-1",
            source_product="linear",
            state={"policy_and_record": "policy and issue"},
            instructions="Is it actionable?",
            threshold=0.95,
            traditional=traditional,
            verdict=lambda value: value,
            typesafe_result=lambda value, _category: value,
        )

    assert result is True
    assert traditional.await_count == expected_traditional_calls
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == expected_decider


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
async def test_traditional_shadow_falls_back_when_typesafe_fails() -> None:
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag",
            return_value="traditional-shadow",
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Cloudflare unavailable"),
        ),
    ):
        result = await run_model_decision(
            team_id=7,
            stage="actionability",
            primary_model="claude-sonnet-5",
            source_id="issue-1",
            source_product="linear",
            state={},
            instructions="Is it actionable?",
            threshold=0.95,
            traditional=AsyncMock(return_value=False),
            verdict=lambda value: value,
            typesafe_result=lambda value, _category: value,
        )

    assert result is False
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "traditional_fallback"


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
async def test_typesafe_only_failure_does_not_run_traditional() -> None:
    traditional = AsyncMock(return_value=True)
    with (
        patch(
            "products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value="typesafe-only"
        ),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture"),
        patch(
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Cloudflare unavailable"),
        ),
    ):
        with pytest.raises(TypesafeDecisionError, match="TypeSafe decision failed") as exc_info:
            await run_model_decision(
                team_id=7,
                stage="actionability",
                primary_model="claude-sonnet-5",
                source_id="issue-1",
                source_product="linear",
                state={},
                instructions="Is it actionable?",
                threshold=0.95,
                traditional=traditional,
                verdict=lambda value: value,
                typesafe_result=lambda value, _category: value,
            )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    traditional.assert_not_awaited()


@pytest.mark.asyncio
async def test_typesafe_only_failure_stops_actionability_batch() -> None:
    output = SignalEmitterOutput("test", "test", "record-1", "description", 1.0, {})
    with (
        patch("products.signals.backend.emission.pipeline.build_async_anthropic_client"),
        patch(
            "products.signals.backend.emission.pipeline.check_actionability",
            AsyncMock(side_effect=TypesafeDecisionError("failed")),
        ),
        patch("products.signals.backend.emission.pipeline.activity"),
    ):
        with pytest.raises(ExceptionGroup) as exc_info:
            await filter_actionable(MagicMock(id=1), [output], "prompt {description}", extra={})

    assert any(isinstance(error, TypesafeDecisionError) for error in exc_info.value.exceptions)


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
@pytest.mark.parametrize("mode", ["typesafe-shadow", "traditional-shadow"])
async def test_malformed_typesafe_response_keeps_pipeline_running(mode: str) -> None:
    with (
        patch("products.signals.backend.typesafe_decision.posthoganalytics.get_feature_flag", return_value=mode),
        patch("products.signals.backend.typesafe_decision.posthoganalytics.capture") as capture,
        patch(
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            return_value=_MalformedCloudflareResponse(),
        ),
    ):
        result = await run_model_decision(
            team_id=7,
            stage="actionability",
            primary_model="claude-sonnet-5",
            source_id="issue-1",
            source_product="linear",
            state={},
            instructions="Is it actionable?",
            threshold=0.95,
            traditional=AsyncMock(return_value=False),
            verdict=lambda value: value,
            typesafe_result=lambda value, _category: value,
        )

    assert result is False
    assert capture.call_args.kwargs["properties"]["typesafe_status"] == "KeyError"


@pytest.mark.asyncio
@override_settings(
    SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID="account",
    SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN="test-token",
)
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
            "products.signals.backend.typesafe_decision.cloudflare_ai_request",
            new_callable=AsyncMock,
            return_value=_CloudflareResponse(),
        ),
    ):
        result = await run_model_decision(
            team_id=7,
            stage="actionability",
            primary_model="claude-sonnet-5",
            source_id="issue-1",
            source_product="linear",
            state={},
            instructions="Is it actionable?",
            threshold=0.95,
            traditional=AsyncMock(return_value=False),
            verdict=lambda value: value,
            typesafe_result=invalid_result,
        )

    assert result is False
    assert capture.call_args.kwargs["properties"]["typesafe_status"] == "ValueError"
    assert capture.call_args.kwargs["properties"]["deciding_provider"] == "traditional_fallback"
