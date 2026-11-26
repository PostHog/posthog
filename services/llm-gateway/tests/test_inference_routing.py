from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
    LiteLLMMessagesToCompletionTransformationHandler,
)

from llm_gateway.api.handler import ProviderError
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.baseten import make_baseten_anthropic_call
from llm_gateway.cloudflare import make_cloudflare_anthropic_call
from llm_gateway.config import Settings
from llm_gateway.inference_routing import (
    normalize_glm_anthropic_request,
    send_inference_anthropic_messages,
    send_inference_chat_completions,
    send_inference_responses,
)
from llm_gateway.modal import make_modal_anthropic_call

GLM_MODEL = "@cf/zai-org/glm-5.2"
GLM53_MODEL = "zai-org/glm-5.3"
CLOUDFLARE_GLM53_MODEL = "@cf/zai-org/glm-5.3"
GLM53_FLASH_MODEL = "zai-org/glm-5.3-flash"
DEEPSEEK_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
UNPRICED_CF_MODEL = "@cf/meta/llama-3.3-70b-instruct"
PRODUCT = "posthog_code"

SURFACES = [
    (send_inference_anthropic_messages, "modal_anthropic_messages", "cloudflare_anthropic_messages"),
    (send_inference_chat_completions, "modal_chat_completions", "cloudflare_chat_completions"),
    (send_inference_responses, "modal_responses", "cloudflare_responses"),
]


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=1, team_id=1, auth_method="oauth_access_token", distinct_id="d-1")


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "cloudflare_api_key": "cf-key",
        "cloudflare_account_id": "cf-account",
        "baseten_api_base": "https://inference.baseten.co/v1",
        "modal_api_base": "https://posthog--glm.us-east.modal.direct/v1",
        "modal_key": "wk-test",
        "modal_secret": "ws-test",
    }
    base.update(overrides)
    return Settings(**base)


async def _send(
    settings: Settings,
    handle: AsyncMock,
    send_fn: Any = send_inference_anthropic_messages,
    product: str = PRODUCT,
    request_data: dict[str, Any] | None = None,
) -> Any:
    with (
        patch("llm_gateway.inference_routing.get_settings", return_value=settings),
        patch("llm_gateway.inference_routing.handle_llm_request", handle),
    ):
        return await send_fn(
            request_data or {"model": GLM_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            _user(),
            False,
            product,
        )


def _called_providers(handle: AsyncMock) -> list[str]:
    return [call.kwargs["provider_config"].name for call in handle.call_args_list]


async def test_glm52_routes_to_modal_without_baseten() -> None:
    handle = AsyncMock(return_value={"ok": True})
    result = await _send(_settings(), handle)
    assert result == {"ok": True}
    assert _called_providers(handle) == ["modal"]
    # The public model id must reach handle_llm_request unchanged — it drives metrics and the
    # unsupported-model gate.
    assert handle.call_args.kwargs["model"] == GLM_MODEL


async def test_glm52_never_falls_back_to_cloudflare() -> None:
    # Cloudflare retired GLM 5.2, so a missing Baseten and Modal backend is a configuration error.
    handle = AsyncMock(return_value={"ok": True})

    with pytest.raises(HTTPException) as exc_info:
        await _send(_settings(modal_api_base=None), handle)

    assert exc_info.value.status_code == 503
    handle.assert_not_called()


async def test_cloudflare_served_model_routes_to_cloudflare() -> None:
    handle = AsyncMock(return_value={"ok": True})
    request = {"model": CLOUDFLARE_GLM53_MODEL, "messages": [{"role": "user", "content": "hi"}]}

    await _send(_settings(baseten_api_key="baseten-key"), handle, request_data=request)

    assert _called_providers(handle) == ["cloudflare"]
    assert handle.call_args.kwargs["model"] == CLOUDFLARE_GLM53_MODEL


@pytest.mark.parametrize("effort", ["high", "max"])
async def test_normalizes_supported_reasoning_effort_for_anthropic_requests(effort: str) -> None:
    request = {
        "model": GLM_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "output_config": {"effort": effort},
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
    }
    handle = AsyncMock(return_value={"ok": True})

    await _send(_settings(), handle, request_data=request)

    assert handle.call_args.kwargs["request_data"] == {
        **request,
        "thinking": {"type": "adaptive"},
    }


def test_drops_clear_thinking_when_no_effort_enables_thinking() -> None:
    # Edit-level rules live in test_anthropic_request.py; this pins that GLM still applies them
    # once its effort upgrade has had a chance to enable thinking.
    request = {
        "model": GLM_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
    }

    assert "context_management" not in normalize_glm_anthropic_request(request, product=PRODUCT)


@pytest.mark.parametrize(("send_fn", "modal_endpoint", "cloudflare_endpoint"), SURFACES)
async def test_each_surface_routes_to_its_provider_configs(
    send_fn: Any, modal_endpoint: str, cloudflare_endpoint: str
) -> None:
    # Every GLM surface must dispatch to its own per-backend ProviderConfig — a mixed-up pairing
    # would mislabel metrics and use the wrong litellm adapter.
    handle = AsyncMock(return_value={"ok": True})
    await _send(_settings(), handle, send_fn=send_fn)
    assert handle.call_args.kwargs["provider_config"].endpoint_name == modal_endpoint

    handle.reset_mock()
    request = {"model": CLOUDFLARE_GLM53_MODEL, "messages": [{"role": "user", "content": "hi"}]}
    await _send(_settings(), handle, send_fn=send_fn, request_data=request)
    assert handle.call_args.kwargs["provider_config"].endpoint_name == cloudflare_endpoint


@pytest.mark.parametrize(
    ("send_fn", "endpoint"), [(row[0], f"baseten_{row[2].removeprefix('cloudflare_')}") for row in SURFACES]
)
async def test_configured_baseten_serves_public_glm_on_each_surface(send_fn: Any, endpoint: str) -> None:
    handle = AsyncMock(return_value={"ok": True})
    settings = _settings(baseten_api_key="baseten-key")

    await _send(settings, handle, send_fn=send_fn)

    assert handle.call_args.kwargs["provider_config"].endpoint_name == endpoint


@pytest.mark.parametrize("model", [DEEPSEEK_MODEL, GLM53_MODEL, GLM53_FLASH_MODEL])
@pytest.mark.parametrize(
    ("send_fn", "endpoint"), [(row[0], f"baseten_{row[2].removeprefix('cloudflare_')}") for row in SURFACES]
)
async def test_baseten_exclusive_models_route_each_surface_directly_to_baseten(
    send_fn: Any, endpoint: str, model: str
) -> None:
    handle = AsyncMock(return_value={"ok": True})
    request = {"model": model, "messages": [{"role": "user", "content": "hi"}]}

    await _send(_settings(baseten_api_key="baseten-key"), handle, send_fn=send_fn, request_data=request)

    assert handle.call_args.kwargs["provider_config"].endpoint_name == endpoint
    assert handle.call_args.kwargs["model"] == model


@pytest.mark.parametrize(
    ("send_fn", "endpoint"), [(row[0], f"baseten_{row[2].removeprefix('cloudflare_')}") for row in SURFACES]
)
async def test_baseten_exclusive_model_case_variants_are_canonicalized(send_fn: Any, endpoint: str) -> None:
    handle = AsyncMock(return_value={"ok": True})
    request = {"model": "ZAI-Org/GLM-5.3", "messages": [{"role": "user", "content": "hi"}]}

    await _send(_settings(baseten_api_key="baseten-key"), handle, send_fn=send_fn, request_data=request)

    assert handle.call_args.kwargs["provider_config"].endpoint_name == endpoint
    assert handle.call_args.kwargs["model"] == GLM53_MODEL


async def test_deepseek_does_not_apply_glm_anthropic_normalization() -> None:
    handle = AsyncMock(return_value={"ok": True})
    request = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "output_config": {"effort": "high"},
    }

    await _send(_settings(baseten_api_key="baseten-key"), handle, request_data=request)

    assert handle.call_args.kwargs["request_data"] == request


@pytest.mark.parametrize("model", [GLM53_MODEL, GLM53_FLASH_MODEL])
async def test_baseten_exclusive_glm_still_applies_anthropic_normalization(model: str) -> None:
    # A Baseten-exclusive GLM is still a GLM: the Claude-runtime reasoning rewrite must apply.
    handle = AsyncMock(return_value={"ok": True})
    request = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "output_config": {"effort": "high"},
    }

    await _send(_settings(baseten_api_key="baseten-key"), handle, request_data=request)

    assert handle.call_args.kwargs["request_data"] == {**request, "thinking": {"type": "adaptive"}}


async def test_configured_baseten_does_not_capture_other_cloudflare_models() -> None:
    handle = AsyncMock(return_value={"ok": True})
    request = {"model": UNPRICED_CF_MODEL, "messages": [{"role": "user", "content": "hi"}]}

    with pytest.raises(HTTPException) as exc_info:
        await _send(_settings(baseten_api_key="baseten-key"), handle, request_data=request)

    assert exc_info.value.status_code == 400
    assert "not supported on the cloudflare provider" in exc_info.value.detail["error"]["message"]
    handle.assert_not_called()


@pytest.mark.parametrize(
    ("settings", "expected_provider"),
    [
        (_settings(), "modal"),
        (_settings(baseten_api_key="baseten-key"), "baseten"),
    ],
)
async def test_provider_failure_propagates_without_cross_backend_retry(
    settings: Settings, expected_provider: str
) -> None:
    handle = AsyncMock(
        side_effect=ProviderError(
            status_code=502, detail={"error": {"message": "boom", "type": "api_error", "code": None}}
        )
    )
    with pytest.raises(HTTPException) as exc_info:
        await _send(settings, handle)
    assert exc_info.value.status_code == 502
    assert _called_providers(handle) == [expected_provider]


@pytest.mark.parametrize(
    ("make_call", "model"),
    [
        pytest.param(
            lambda: make_cloudflare_anthropic_call("https://cf.test/v1", "cf-key"), GLM_MODEL, id="cloudflare"
        ),
        pytest.param(
            lambda: make_modal_anthropic_call("https://modal.test/v1", "wk", "ws"), "moonshotai/kimi-k3", id="modal"
        ),
        pytest.param(
            lambda: make_baseten_anthropic_call("https://baseten.test/v1", "bt-key"), DEEPSEEK_MODEL, id="baseten"
        ),
    ],
)
async def test_anthropic_calls_convert_enabled_thinking_to_adaptive(make_call: Any, model: str) -> None:
    # litellm reroutes provider="openai" requests with enabled thinking through OpenAI's Responses
    # API ("responses/" model prefix), which 400s on these chat/completions-only backends.
    handler = AsyncMock(return_value={"ok": True})
    with patch.object(LiteLLMMessagesToCompletionTransformationHandler, "async_anthropic_messages_handler", handler):
        await make_call()(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            thinking={"type": "enabled", "budget_tokens": 31999},
        )

    assert handler.call_args.kwargs["thinking"] == {"type": "adaptive"}
    assert handler.call_args.kwargs["output_config"] == {"effort": "high"}
