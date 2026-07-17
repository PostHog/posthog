from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from llm_gateway.rate_limiting.model_cost_service import ModelCost

# Bridge entries for models not yet in LiteLLM's upstream cost map. The gateway
# derives /v1/models (and billing cost) from that map, so a model missing upstream
# is invisible even when allowlisted in products/config.py. Merged only when
# LiteLLM doesn't already define the model; delete each entry once upstream lands it.
# Pricing verified against OpenRouter (Anthropic + Bedrock).
MODEL_COST_OVERRIDES: Final[dict[str, ModelCost]] = {
    "claude-fable-5": {
        "litellm_provider": "anthropic",
        "mode": "chat",
        # 200k not 1M: the 1M window is a beta-header feature, same as opus-4.x.
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
        "input_cost_per_token": 1e-05,
        "output_cost_per_token": 5e-05,
        "cache_read_input_token_cost": 1e-06,
        "cache_creation_input_token_cost": 1.25e-05,
        "supports_vision": True,
        "supports_prompt_caching": True,
    },
    "gpt-5.6-sol": {
        "litellm_provider": "openai",
        "mode": "responses",
        "max_input_tokens": 1_050_000,
        "max_output_tokens": 128_000,
        "input_cost_per_token": 5e-06,
        "output_cost_per_token": 3e-05,
        "cache_read_input_token_cost": 5e-07,
        "cache_creation_input_token_cost": 6.25e-06,
        "supports_vision": True,
        "supports_prompt_caching": True,
    },
    "gpt-5.6-terra": {
        "litellm_provider": "openai",
        "mode": "responses",
        "max_input_tokens": 1_050_000,
        "max_output_tokens": 128_000,
        "input_cost_per_token": 2.5e-06,
        "output_cost_per_token": 1.5e-05,
        "cache_read_input_token_cost": 2.5e-07,
        "cache_creation_input_token_cost": 3.125e-06,
        "supports_vision": True,
        "supports_prompt_caching": True,
    },
    "gpt-5.6-luna": {
        "litellm_provider": "openai",
        "mode": "responses",
        "max_input_tokens": 1_050_000,
        "max_output_tokens": 128_000,
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 6e-06,
        "cache_read_input_token_cost": 1e-07,
        "cache_creation_input_token_cost": 1.25e-06,
        "supports_vision": True,
        "supports_prompt_caching": True,
    },
}


def apply_model_cost_overrides(model_cost: dict[str, ModelCost]) -> dict[str, ModelCost]:
    """Fill bridge entries LiteLLM doesn't define, in place. Upstream always wins."""
    for model_id, cost in MODEL_COST_OVERRIDES.items():
        if model_id not in model_cost:
            model_cost[model_id] = cast("ModelCost", dict(cost))
    return model_cost
