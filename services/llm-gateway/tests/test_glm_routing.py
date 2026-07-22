from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway.api.handler import ProviderError
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import Settings
from llm_gateway.glm_routing import (
    send_glm_anthropic_messages,
    send_glm_chat_completions,
    send_glm_responses,
)
from llm_gateway.request_context import RequestContext, set_request_context

GLM_MODEL = "@cf/zai-org/glm-5.2"
PRODUCT = "posthog_code"

SURFACES = [
    (send_glm_anthropic_messages, "modal_anthropic_messages", "cloudflare_anthropic_messages"),
    (send_glm_chat_completions, "modal_chat_completions", "cloudflare_chat_completions"),
    (send_glm_responses, "modal_responses", "cloudflare_responses"),
]


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=1, team_id=1, auth_method="oauth_access_token", distinct_id="d-1")


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "cloudflare_api_key": "cf-key",
        "cloudflare_account_id": "cf-account",
        "modal_api_base": "https://posthog--glm.us-east.modal.direct/v1",
        "modal_key": "wk-test",
        "modal_secret": "ws-test",
    }
    base.update(overrides)
    return Settings(**base)


async def _send(
    settings: Settings,
    handle: AsyncMock,
    flag: bool | None = None,
    send_fn: Any = send_glm_anthropic_messages,
    product: str = PRODUCT,
) -> tuple[Any, AsyncMock]:
    evaluate = AsyncMock(return_value=flag)
    with (
        patch("llm_gateway.glm_routing.get_settings", return_value=settings),
        patch("llm_gateway.glm_routing.handle_llm_request", handle),
        patch("llm_gateway.glm_routing.evaluate_flag", evaluate),
    ):
        result = await send_fn(
            {"model": GLM_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            _user(),
            False,
            product,
        )
    return result, evaluate


def _called_providers(handle: AsyncMock) -> list[str]:
    return [call.kwargs["provider_config"].name for call in handle.call_args_list]


async def test_routes_to_cloudflare_by_default() -> None:
    handle = AsyncMock(return_value={"ok": True})
    result, _ = await _send(_settings(), handle)
    assert result == {"ok": True}
    assert _called_providers(handle) == ["cloudflare"]
    # The public model id must reach handle_llm_request unchanged — it drives metrics and the
    # unsupported-model gate.
    assert handle.call_args.kwargs["model"] == GLM_MODEL


async def test_routes_to_modal_when_fraction_one_without_flag_roundtrip() -> None:
    # A guaranteed-Modal route must not pay (or depend on) a remote flag evaluation.
    handle = AsyncMock(return_value={"ok": True})
    result, evaluate = await _send(_settings(glm_modal_traffic_fraction=1.0), handle)
    assert result == {"ok": True}
    assert _called_providers(handle) == ["modal"]
    assert handle.call_args.kwargs["model"] == GLM_MODEL
    evaluate.assert_not_called()


async def test_modal_only_configuration_routes_to_modal() -> None:
    # With Cloudflare creds absent, GLM is still advertised (it has a Modal backend) — routing must
    # not send those requests to Cloudflare's 503, whatever the flag/fraction say.
    handle = AsyncMock(return_value={"ok": True})
    _, evaluate = await _send(_settings(cloudflare_api_key=None, cloudflare_account_id=None), handle, flag=False)
    assert _called_providers(handle) == ["modal"]
    evaluate.assert_not_called()


@pytest.mark.parametrize(("send_fn", "modal_endpoint", "cloudflare_endpoint"), SURFACES)
async def test_each_surface_routes_to_its_provider_configs(
    send_fn: Any, modal_endpoint: str, cloudflare_endpoint: str
) -> None:
    # Every GLM surface must dispatch to its own per-backend ProviderConfig — a mixed-up pairing
    # would mislabel metrics and use the wrong litellm adapter.
    handle = AsyncMock(return_value={"ok": True})
    _, _ = await _send(_settings(glm_modal_traffic_fraction=1.0), handle, send_fn=send_fn)
    assert handle.call_args.kwargs["provider_config"].endpoint_name == modal_endpoint

    handle.reset_mock()
    _, _ = await _send(_settings(), handle, send_fn=send_fn)
    assert handle.call_args.kwargs["provider_config"].endpoint_name == cloudflare_endpoint


@pytest.mark.parametrize("product", ["twig", "array"])
async def test_alias_products_ramp_through_canonical_fraction(product: str) -> None:
    # twig/array requests must follow posthog_code's per-product ramp end to end.
    handle = AsyncMock(return_value={"ok": True})
    settings = _settings(glm_modal_product_traffic_fractions={"posthog_code": 1.0})
    _, evaluate = await _send(settings, handle, product=product)
    assert _called_providers(handle) == ["modal"]
    evaluate.assert_not_called()


async def test_flag_opts_into_modal_at_fraction_zero() -> None:
    handle = AsyncMock(return_value={"ok": True})
    _, _ = await _send(_settings(), handle, flag=True)
    assert _called_providers(handle) == ["modal"]


async def test_forwarded_flag_header_cannot_force_modal() -> None:
    # x-posthog-flag-* headers come from any authenticated caller — they must not override the
    # server-side flag/fraction, or a client could pin itself to a backend operators turned off.
    handle = AsyncMock(return_value={"ok": True})
    set_request_context(RequestContext(request_id="test", posthog_flags={"tasks-glm-modal-inference": "true"}))
    _, _ = await _send(_settings(), handle, flag=False)
    assert _called_providers(handle) == ["cloudflare"]


async def test_modal_failure_propagates_without_cross_backend_retry() -> None:
    # A silent Cloudflare retry would mask Modal degradation from the rollback decision and double
    # provider spend under a Modal outage.
    handle = AsyncMock(
        side_effect=ProviderError(
            status_code=502, detail={"error": {"message": "boom", "type": "api_error", "code": None}}
        )
    )
    with pytest.raises(HTTPException) as exc_info:
        await _send(_settings(glm_modal_traffic_fraction=1.0), handle)
    assert exc_info.value.status_code == 502
    assert _called_providers(handle) == ["modal"]
