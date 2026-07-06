from unittest.mock import AsyncMock, patch

import litellm
import pytest
from fastapi import HTTPException
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
    LiteLLMMessagesToCompletionTransformationHandler,
)
from litellm.types.utils import ModelResponse

from llm_gateway.cloudflare import (
    CLOUDFLARE_ALLOWED_MODELS,
    _inject_cloudflare_params,
    ensure_cloudflare_model_allowed,
    make_cloudflare_responses_call,
)
from llm_gateway.rate_limiting.cost_refresh import COST_ALIASES


def test_inject_cloudflare_params_prefix_matches_cost_alias_keys() -> None:
    kwargs: dict = {"model": "@cf/moonshotai/kimi-k2.6"}
    _inject_cloudflare_params(kwargs, "https://api.cloudflare.com/test/ai/v1", "secret")

    assert kwargs["model"] == "openai/@cf/moonshotai/kimi-k2.6"
    assert kwargs["api_base"] == "https://api.cloudflare.com/test/ai/v1"
    assert kwargs["api_key"] == "secret"
    # Load-bearing: if this fails, _inject_cloudflare_params and COST_ALIASES no
    # longer agree on the prefix and cost lookup silently misses in production.
    assert kwargs["model"] in COST_ALIASES


def test_inject_cloudflare_params_defaults_drop_params_true() -> None:
    # CF routes through litellm's OpenAI-compatible surface, which 400s on provider-specific params
    # (Anthropic's reasoning_effort etc.). drop_params must default on so those are dropped, not fatal.
    kwargs: dict = {"model": "@cf/zai-org/glm-5.2"}
    _inject_cloudflare_params(kwargs, "https://api.cloudflare.com/test/ai/v1", "secret")
    assert kwargs["drop_params"] is True


def test_inject_cloudflare_params_preserves_explicit_drop_params() -> None:
    # setdefault semantics: a caller that explicitly opts out keeps their value.
    kwargs: dict = {"model": "@cf/zai-org/glm-5.2", "drop_params": False}
    _inject_cloudflare_params(kwargs, "https://api.cloudflare.com/test/ai/v1", "secret")
    assert kwargs["drop_params"] is False


def test_allowlist_derived_from_cost_aliases() -> None:
    # Any @cf/ entry in COST_ALIASES must be reachable through the allowlist,
    # otherwise we'd have a priced model we refuse to route.
    expected = {alias.removeprefix("openai/") for alias in COST_ALIASES if alias.startswith("openai/@cf/")}
    assert CLOUDFLARE_ALLOWED_MODELS == expected
    assert "@cf/moonshotai/kimi-k2.6" in CLOUDFLARE_ALLOWED_MODELS
    assert "@cf/zai-org/glm-5.2" in CLOUDFLARE_ALLOWED_MODELS


@pytest.mark.parametrize("model", ["@cf/moonshotai/kimi-k2.6", "@cf/zai-org/glm-5.2"])
def test_ensure_cloudflare_model_allowed_accepts_priced_model(model: str) -> None:
    ensure_cloudflare_model_allowed(model)


@pytest.mark.parametrize(
    "model",
    [
        "@cf/meta/llama-3.3-70b-instruct",
        "@cf/openai/gpt-oss-120b",
        "@cf/unknown/model",
    ],
)
def test_ensure_cloudflare_model_allowed_rejects_unpriced_model(model: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_cloudflare_model_allowed(model)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["type"] == "invalid_request_error"
    assert model in exc_info.value.detail["error"]["message"]


def test_litellm_anthropic_messages_adapter_contract() -> None:
    # Fails in CI if a litellm bump renames the experimental symbol the CF anthropic route imports.
    assert callable(LiteLLMMessagesToCompletionTransformationHandler.async_anthropic_messages_handler)


async def test_make_cloudflare_responses_call_injects_params_and_forces_bridge() -> None:
    # The CF responses adapter must inject CF creds/model and force litellm's
    # Responses->chat/completions bridge (use_chat_completions_api=True), since CF's
    # OpenAI-compatible endpoint has no native /responses route.
    llm_call = make_cloudflare_responses_call("https://api.cloudflare.com/test/ai/v1", "secret")

    with patch("llm_gateway.cloudflare.litellm.aresponses", new=AsyncMock(return_value="ok")) as mock_aresponses:
        await llm_call(model="@cf/zai-org/glm-5.2", input="hi")

    kwargs = mock_aresponses.call_args.kwargs
    assert kwargs["use_chat_completions_api"] is True
    assert kwargs["model"] == "openai/@cf/zai-org/glm-5.2"
    assert kwargs["api_base"] == "https://api.cloudflare.com/test/ai/v1"
    assert kwargs["api_key"] == "secret"
    assert kwargs["input"] == "hi"


async def test_make_cloudflare_responses_call_ignores_caller_supplied_bridge_flag() -> None:
    # ResponsesRequest allows extra fields, so a caller can smuggle use_chat_completions_api into
    # the request body. The adapter must overwrite it (not pass it twice -> TypeError, and not let
    # False escape the bridge onto CF's missing /responses route).
    llm_call = make_cloudflare_responses_call("https://api.cloudflare.com/test/ai/v1", "secret")

    with patch("llm_gateway.cloudflare.litellm.aresponses", new=AsyncMock(return_value="ok")) as mock_aresponses:
        # Caller tries to disable the bridge; must not raise and must not win.
        await llm_call(model="@cf/zai-org/glm-5.2", input="hi", use_chat_completions_api=False)

    assert mock_aresponses.call_args.kwargs["use_chat_completions_api"] is True


async def test_litellm_responses_completion_bridge_contract() -> None:
    # Load-bearing: litellm.aresponses(use_chat_completions_api=True, ...) must route a CF-style
    # model through the chat/completions bridge (i.e. call litellm.acompletion), not the native
    # Responses API. Fails fast if a litellm bump drops/renames the flag — which would silently
    # send CF responses traffic back to the broken native path.
    fake = ModelResponse(choices=[{"message": {"role": "assistant", "content": "hi from cf"}}])

    with patch("litellm.acompletion", new=AsyncMock(return_value=fake)) as mock_acompletion:
        result = await litellm.aresponses(
            model="openai/@cf/zai-org/glm-5.2",
            input="hello",
            use_chat_completions_api=True,
            api_base="https://api.cloudflare.com/test/ai/v1",
            api_key="secret",
        )

    assert mock_acompletion.called
    assert mock_acompletion.call_args.kwargs["api_base"] == "https://api.cloudflare.com/test/ai/v1"
    # The bridge must not leak the gateway-internal flag downstream to acompletion.
    assert "use_chat_completions_api" not in mock_acompletion.call_args.kwargs
    assert type(result).__name__ == "ResponsesAPIResponse"
