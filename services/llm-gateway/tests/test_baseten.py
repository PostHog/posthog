from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway.baseten import (
    BASETEN_METRIC_MODEL,
    _inject_baseten_params,
    ensure_baseten_configured,
    make_baseten_responses_call,
)
from llm_gateway.config import Settings
from llm_gateway.rate_limiting.cost_refresh import COST_ALIASES, normalize_metric_labels
from llm_gateway.rate_limiting.model_cost_overrides import MODEL_COST_OVERRIDES

GLM_MODEL = "@cf/zai-org/glm-5.2"
BASETEN_MODEL = "openai/zai-org/GLM-5.2"


def test_inject_baseten_params_maps_model_and_pins_api_key() -> None:
    kwargs: dict[str, Any] = {
        "model": GLM_MODEL,
        "headers": {"Host": "attacker.example"},
        "extra_headers": {"Authorization": "Bearer attacker", "X-Other": "no"},
    }

    _inject_baseten_params(kwargs, "https://inference.baseten.co/v1", "test-key")

    assert kwargs["model"] == BASETEN_MODEL
    assert kwargs["api_base"] == "https://inference.baseten.co/v1"
    assert "headers" not in kwargs
    assert kwargs["extra_headers"] == {"Authorization": "Api-Key test-key"}
    assert kwargs["drop_params"] is True
    assert COST_ALIASES[BASETEN_MODEL] == (BASETEN_METRIC_MODEL, "openai")
    assert MODEL_COST_OVERRIDES[BASETEN_METRIC_MODEL]["input_cost_per_token"] == 1.4e-06
    assert MODEL_COST_OVERRIDES[BASETEN_METRIC_MODEL]["cache_read_input_token_cost"] == 1.4e-07
    assert MODEL_COST_OVERRIDES[BASETEN_METRIC_MODEL]["output_cost_per_token"] == 4.4e-06
    assert normalize_metric_labels(BASETEN_MODEL, "openai") == ("baseten", "baseten/zai-org/glm-5.2")


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
