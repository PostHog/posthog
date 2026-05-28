from llm_gateway.cloudflare import _inject_cloudflare_params
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
