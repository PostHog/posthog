from typing import Any

import litellm
from fastapi import HTTPException

from llm_gateway.rate_limiting.model_cost_service import ModelCostService

_BEDROCK_ANTHROPIC_MODEL_TARGETS: dict[str, str] = {
    "claude-opus-4-5": "bedrock/anthropic.claude-opus-4-5-20250929-v1:0",
    "claude-opus-4-5-20260101": "bedrock/anthropic.claude-opus-4-5-20250929-v1:0",
    "claude-opus-4-6": "bedrock/anthropic.claude-opus-4-6-v1:0",
    "claude-sonnet-4-5": "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-3-5-sonnet-20241022": "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5-20260101": "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-6": "bedrock/anthropic.claude-sonnet-4-6-v1:0",
    "claude-haiku-4-5": "bedrock/anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5-20251001": "bedrock/anthropic.claude-haiku-4-5-20251001-v1:0",
}


def ensure_bedrock_configured(settings: Any) -> None:
    if settings.bedrock_region_name:
        return
    raise HTTPException(
        status_code=503,
        detail={"error": {"message": "Bedrock region not configured", "type": "configuration_error"}},
    )


def map_anthropic_model_to_bedrock(model: str) -> str:
    bedrock_model = _BEDROCK_ANTHROPIC_MODEL_TARGETS.get(model.lower())
    if bedrock_model is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"Model '{model}' is not available on Bedrock Anthropic routing",
                    "type": "invalid_request_error",
                }
            },
        )
    all_models = ModelCostService.get_instance().get_all_models()
    if bedrock_model not in all_models:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": (
                        f"Bedrock model '{bedrock_model}' is not available in LiteLLM model map; "
                        "refresh model costs or update mapping"
                    ),
                    "type": "configuration_error",
                }
            },
        )
    return bedrock_model


def count_tokens_with_bedrock(messages: list[dict[str, Any]], model: str, aws_region_name: str) -> int:
    mapped_model = map_anthropic_model_to_bedrock(model)
    return litellm.token_counter(model=mapped_model, messages=messages, aws_region_name=aws_region_name)
