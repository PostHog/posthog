from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway.config import Settings
from llm_gateway.modal import (
    MODAL_ALLOWED_MODELS,
    MODAL_MODEL_MAP,
    _inject_modal_params,
    ensure_modal_model_allowed,
    make_modal_responses_call,
    should_route_glm_to_modal,
)
from llm_gateway.rate_limiting.cost_refresh import ALIAS_METRIC_LABELS, COST_ALIASES

GLM_MODEL = "@cf/zai-org/glm-5.2"


def _modal_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "modal_api_base": "https://posthog--glm.us-east.modal.direct/v1",
        "modal_key": "wk-test",
        "modal_secret": "ws-test",
    }
    base.update(overrides)
    return Settings(**base)


def test_inject_modal_params_maps_model_and_pins_proxy_auth() -> None:
    # Caller-supplied header dicts (`headers` or `extra_headers`, any casing) must never reach the
    # authenticated upstream request — litellm merges both into the outbound headers, and a
    # forwarded Host header would exfiltrate the proxy-token pair.
    kwargs: dict = {
        "model": GLM_MODEL,
        "headers": {"Host": "attacker.example"},
        "extra_headers": {"MODAL-KEY": "attacker", "host": "attacker.example", "X-Other": "no"},
    }
    _inject_modal_params(kwargs, "https://modal.test/v1", "wk", "ws")

    assert kwargs["model"] == "openai/zai-org/GLM-5.2-FP8"
    assert kwargs["api_base"] == "https://modal.test/v1"
    # litellm's OpenAI client rejects a missing api_key even though Modal auth is header-based.
    assert kwargs["api_key"]
    assert "headers" not in kwargs
    assert kwargs["extra_headers"] == {"Modal-Key": "wk", "Modal-Secret": "ws"}
    # Load-bearing: if this fails, the litellm model key is unpriced/unlabeled and cost lookup
    # silently falls to default_fallback_cost_usd (and metrics lose the modal provider label).
    assert kwargs["model"] in COST_ALIASES
    assert kwargs["model"] in ALIAS_METRIC_LABELS


@pytest.mark.parametrize(("initial", "expected"), [({}, True), ({"drop_params": False}, False)])
def test_inject_modal_params_drop_params(initial: dict, expected: bool) -> None:
    # drop_params must default on (the OpenAI-compatible surface 400s on Anthropic-only params)
    # while an explicit caller opt-out keeps its value.
    kwargs: dict = {"model": GLM_MODEL, **initial}
    _inject_modal_params(kwargs, "https://modal.test/v1", "wk", "ws")
    assert kwargs["drop_params"] is expected


def test_modal_model_map_served_names_all_priced_and_labeled() -> None:
    # An unpriced Modal model would bill the flat fallback cost; the label must keep the public id
    # so one model id slices across backends in dashboards.
    for public_id, served in MODAL_MODEL_MAP.items():
        litellm_key = f"openai/{served}"
        assert litellm_key in COST_ALIASES
        provider, metric_model = ALIAS_METRIC_LABELS[litellm_key]
        assert provider == "modal"
        assert metric_model == public_id


def test_ensure_modal_model_allowed_accepts_mapped_model() -> None:
    ensure_modal_model_allowed(GLM_MODEL)
    assert GLM_MODEL in MODAL_ALLOWED_MODELS


@pytest.mark.parametrize("model", ["@cf/moonshotai/kimi-k2.6", "@cf/unknown/model", "zai-org/GLM-5.2-FP8"])
def test_ensure_modal_model_allowed_rejects_unmapped_model(model: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_modal_model_allowed(model)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["type"] == "invalid_request_error"
    assert model in exc_info.value.detail["error"]["message"]


@pytest.mark.parametrize(
    ("fraction", "product_fractions", "configured", "expected"),
    [
        (0.0, {}, True, False),
        (1.0, {}, True, True),
        # Missing credentials beat any fraction.
        (1.0, {}, False, False),
        # Per-product override beats the global fraction in both directions.
        (0.0, {"posthog_code": 1.0}, True, True),
        (1.0, {"posthog_code": 0.0}, True, False),
    ],
)
def test_should_route_glm_to_modal(
    fraction: float, product_fractions: dict[str, float], configured: bool, expected: bool
) -> None:
    overrides: dict[str, Any] = {
        "glm_modal_traffic_fraction": fraction,
        "glm_modal_product_traffic_fractions": product_fractions,
    }
    if not configured:
        overrides["modal_key"] = None
    settings = _modal_settings(**overrides)
    assert (
        should_route_glm_to_modal(GLM_MODEL, product="posthog_code", user_key="user-1", settings=settings) is expected
    )


@pytest.mark.parametrize("product", ["twig", "array"])
def test_product_aliases_resolve_in_fraction_lookup(product: str) -> None:
    # Legacy aliases must read posthog_code's per-product fraction, or its ramp/rollback would
    # silently skip alias traffic.
    settings = _modal_settings(
        glm_modal_traffic_fraction=0.0, glm_modal_product_traffic_fractions={"posthog_code": 1.0}
    )
    assert should_route_glm_to_modal(GLM_MODEL, product=product, user_key="user-1", settings=settings) is True


def test_should_route_only_modal_served_models() -> None:
    # kimi is CF-allowlisted but has no Modal-served equivalent; routing it to Modal would 404.
    settings = _modal_settings(glm_modal_traffic_fraction=1.0)
    assert (
        should_route_glm_to_modal("@cf/moonshotai/kimi-k2.6", product="posthog_code", user_key="u", settings=settings)
        is False
    )


def test_partial_fraction_is_sticky_and_monotonic() -> None:
    # Repeat calls must be identical, and a user routed to Modal at fraction f must stay routed at
    # any higher fraction — otherwise each ramp-up step would flap migrated users back.
    fractions = (0.25, 0.5, 0.75)
    settings = [_modal_settings(glm_modal_traffic_fraction=f) for f in fractions]
    for user in ("user-1", "user-2", "user-3", "user-4", "user-5"):
        decisions = [
            should_route_glm_to_modal(GLM_MODEL, product="posthog_code", user_key=user, settings=s) for s in settings
        ]
        assert decisions == sorted(decisions)
        repeat = [
            should_route_glm_to_modal(GLM_MODEL, product="posthog_code", user_key=user, settings=s) for s in settings
        ]
        assert repeat == decisions


def test_partial_fraction_splits_pinned_users() -> None:
    # Pinned user keys with known buckets ("3" -> ~0.25, "2" -> ~0.96) must land on opposite sides
    # of fraction 0.5 — a degenerate bucket (constant 0 or 1) passes the monotonicity test above
    # but fails here.
    settings = _modal_settings(glm_modal_traffic_fraction=0.5)
    assert should_route_glm_to_modal(GLM_MODEL, product="posthog_code", user_key="3", settings=settings) is True
    assert should_route_glm_to_modal(GLM_MODEL, product="posthog_code", user_key="2", settings=settings) is False


async def test_make_modal_responses_call_forces_bridge_and_ignores_smuggled_flag() -> None:
    # vLLM has no /responses route, so the Responses->chat/completions bridge must be forced and a
    # caller-smuggled use_chat_completions_api=False must not escape it (same bug class as CF).
    llm_call = make_modal_responses_call("https://modal.test/v1", "wk", "ws")

    with patch("llm_gateway.modal.litellm.aresponses", new=AsyncMock(return_value="ok")) as mock_aresponses:
        await llm_call(model=GLM_MODEL, input="hi", use_chat_completions_api=False)

    kwargs = mock_aresponses.call_args.kwargs
    assert kwargs["use_chat_completions_api"] is True
    assert kwargs["model"] == "openai/zai-org/GLM-5.2-FP8"
    assert kwargs["api_base"] == "https://modal.test/v1"
    assert kwargs["extra_headers"]["Modal-Key"] == "wk"
    assert kwargs["extra_headers"]["Modal-Secret"] == "ws"
    assert kwargs["input"] == "hi"
