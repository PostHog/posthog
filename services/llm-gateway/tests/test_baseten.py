from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway.baseten import (
    _inject_baseten_params,
    ensure_baseten_configured,
    make_baseten_responses_call,
)
from llm_gateway.config import Settings
from llm_gateway.rate_limiting.cost_refresh import COST_ALIASES, normalize_metric_labels
from llm_gateway.rate_limiting.model_cost_overrides import MODEL_COST_OVERRIDES

GLM_MODEL = "@cf/zai-org/glm-5.2"
BASETEN_MODEL = "openai/zai-org/GLM-5.2"
DEEPSEEK_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
BASETEN_DEEPSEEK_LITELLM_MODEL = "openai/deepseek-ai/DeepSeek-V4-Flash-0731"
GLM53_MODEL = "zai-org/glm-5.3"
BASETEN_GLM53_LITELLM_MODEL = "openai/zai-org/GLM-5.3"


@pytest.mark.parametrize(
    ("public_model", "litellm_model", "metric_model", "input_cost", "output_cost", "cache_read_cost"),
    [
        (GLM_MODEL, BASETEN_MODEL, "baseten/zai-org/glm-5.2", 1.4e-06, 4.4e-06, 1.4e-07),
        (DEEPSEEK_MODEL, BASETEN_DEEPSEEK_LITELLM_MODEL, f"baseten/{DEEPSEEK_MODEL}", 1.3e-07, 2.6e-07, 2.8e-08),
        (GLM53_MODEL, BASETEN_GLM53_LITELLM_MODEL, f"baseten/{GLM53_MODEL}", 1.4e-06, 4.4e-06, 1.4e-07),
    ],
)
def test_inject_baseten_params_maps_model_and_pins_api_key(
    public_model: str,
    litellm_model: str,
    metric_model: str,
    input_cost: float,
    output_cost: float,
    cache_read_cost: float,
) -> None:
    kwargs: dict[str, Any] = {
        "model": public_model,
        "headers": {"Host": "attacker.example"},
        "extra_headers": {"Authorization": "Bearer attacker", "X-Other": "no"},
    }

    _inject_baseten_params(kwargs, "https://inference.baseten.co/v1", "test-key")

    assert kwargs["model"] == litellm_model
    assert kwargs["api_base"] == "https://inference.baseten.co/v1"
    assert "headers" not in kwargs
    assert kwargs["extra_headers"] == {"Authorization": "Bearer test-key"}
    assert kwargs["drop_params"] is True
    assert COST_ALIASES[litellm_model] == (metric_model, "openai")
    assert MODEL_COST_OVERRIDES[metric_model]["input_cost_per_token"] == input_cost
    assert MODEL_COST_OVERRIDES[metric_model]["cache_read_input_token_cost"] == cache_read_cost
    assert MODEL_COST_OVERRIDES[metric_model]["output_cost_per_token"] == output_cost
    assert normalize_metric_labels(litellm_model, "openai") == ("baseten", metric_model)


def test_inject_baseten_params_forces_streaming_usage() -> None:
    kwargs: dict[str, Any] = {
        "model": GLM_MODEL,
        "stream": True,
        "stream_options": {"include_usage": False},
    }

    _inject_baseten_params(kwargs, "https://inference.baseten.co/v1", "test-key")

    assert kwargs["stream_options"] == {"include_usage": True, "continuous_usage_stats": True}


def test_ensure_baseten_configured_requires_api_key() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_baseten_configured(Settings())

    assert exc_info.value.status_code == 503


async def test_make_baseten_responses_call_uses_chat_completions_bridge() -> None:
    llm_call = make_baseten_responses_call("https://inference.baseten.co/v1", "test-key")

    with patch("llm_gateway.baseten.litellm.aresponses", new=AsyncMock(return_value="ok")) as mock_aresponses:
        await llm_call(model=GLM_MODEL, input="hi", use_chat_completions_api=False)

    assert mock_aresponses.call_args.kwargs["use_chat_completions_api"] is True
