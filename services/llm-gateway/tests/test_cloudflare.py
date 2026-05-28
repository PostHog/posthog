import pytest
from fastapi import HTTPException

from llm_gateway.cloudflare import (
    CLOUDFLARE_ALLOWED_MODELS,
    _inject_cloudflare_params,
    ensure_cloudflare_model_allowed,
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


def test_allowlist_derived_from_cost_aliases() -> None:
    # Any @cf/ entry in COST_ALIASES must be reachable through the allowlist,
    # otherwise we'd have a priced model we refuse to route.
    expected = {alias.removeprefix("openai/") for alias in COST_ALIASES if alias.startswith("openai/@cf/")}
    assert CLOUDFLARE_ALLOWED_MODELS == expected
    assert "@cf/moonshotai/kimi-k2.6" in CLOUDFLARE_ALLOWED_MODELS


def test_ensure_cloudflare_model_allowed_accepts_priced_model() -> None:
    ensure_cloudflare_model_allowed("@cf/moonshotai/kimi-k2.6")


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
