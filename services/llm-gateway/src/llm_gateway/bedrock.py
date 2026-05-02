from __future__ import annotations

import asyncio
import functools
import json
import os
from typing import Any, Final

import boto3
import structlog
from botocore.config import Config
from fastapi import HTTPException

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

BEDROCK_ANTHROPIC_VERSION: Final[str] = "bedrock-2023-05-31"
DEFAULT_BEDROCK_MAX_TOKENS: Final[int] = 4096

BEDROCK_ANTHROPIC_MODEL_PREFIXES: Final[tuple[str, ...]] = (
    "anthropic.",
    "global.anthropic.",
    "us.anthropic.",
    "eu.anthropic.",
)

# Mapping from Anthropic model names to Bedrock model IDs.
# Keys can be either the short name or the dated variant.
ANTHROPIC_TO_BEDROCK_MODEL_MAP: Final[dict[str, dict[str, str]]] = {
    "claude-opus-4-5": {
        "us": "us.anthropic.claude-opus-4-5-20251101-v1:0",
        "eu": "eu.anthropic.claude-opus-4-5-20251101-v1:0",
    },
    "claude-opus-4-5-20251101": {
        "us": "us.anthropic.claude-opus-4-5-20251101-v1:0",
        "eu": "eu.anthropic.claude-opus-4-5-20251101-v1:0",
    },
    "claude-opus-4-6": {
        "us": "us.anthropic.claude-opus-4-6-v1",
        "eu": "eu.anthropic.claude-opus-4-6-v1",
    },
    "claude-opus-4-7": {
        "us": "us.anthropic.claude-opus-4-7-v1",
        "eu": "eu.anthropic.claude-opus-4-7-v1",
    },
    "claude-sonnet-4-5": {
        "us": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "eu": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    },
    "claude-sonnet-4-5-20250929": {
        "us": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "eu": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    },
    "claude-sonnet-4-6": {
        "us": "us.anthropic.claude-sonnet-4-6",
        "eu": "eu.anthropic.claude-sonnet-4-6",
    },
    "claude-haiku-4-5": {
        "us": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "eu": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    },
    "claude-haiku-4-5-20251001": {
        "us": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "eu": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    },
}

BEDROCK_MODEL_IDS: Final[frozenset[str]] = frozenset(
    model_id for region_map in ANTHROPIC_TO_BEDROCK_MODEL_MAP.values() for model_id in region_map.values()
)


def is_bedrock_model_id(model: str) -> bool:
    return model.startswith(BEDROCK_ANTHROPIC_MODEL_PREFIXES)


def get_bedrock_region_name(settings: object | None = None) -> str | None:
    resolved_settings = settings if settings is not None else get_settings()
    region_name = getattr(resolved_settings, "bedrock_region_name", None)
    if isinstance(region_name, str) and region_name:
        return region_name

    for env_var in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        env_value = os.environ.get(env_var)
        if env_value:
            return env_value
    return None


def is_bedrock_configured(settings: object | None = None) -> bool:
    return get_bedrock_region_name(settings) is not None


def ensure_bedrock_configured(settings: object | None = None) -> str:
    region_name = get_bedrock_region_name(settings)
    if region_name:
        return region_name

    logger.warning("Bedrock region not configured")
    raise HTTPException(
        status_code=503,
        detail={"error": {"message": "Bedrock region not configured", "type": "configuration_error"}},
    )


def _get_bedrock_geo(region_name: str | None) -> str:
    if region_name and region_name.startswith("eu-"):
        return "eu"
    return "us"


def map_to_bedrock_model(model: str, region_name: str | None = None) -> str:
    """Map an Anthropic model name to a Bedrock model ID for the current region."""
    if is_bedrock_model_id(model):
        return model

    region_map = ANTHROPIC_TO_BEDROCK_MODEL_MAP.get(model)
    if region_map is None:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"No Bedrock mapping for model '{model}'", "type": "invalid_request_error"}},
        )

    geo = _get_bedrock_geo(region_name or get_bedrock_region_name())
    return region_map.get(geo, region_map["us"])


def get_bedrock_model_access_candidates(model: str, region_name: str | None = None) -> frozenset[str]:
    if is_bedrock_model_id(model):
        return frozenset({model.lower()})

    region_map = ANTHROPIC_TO_BEDROCK_MODEL_MAP.get(model)
    if region_map is None:
        return frozenset({model.lower()})

    mapped_model = map_to_bedrock_model(model, region_name=region_name)
    return frozenset({model.lower(), mapped_model.lower()})


@functools.lru_cache
def get_bedrock_runtime_client(region_name: str, timeout_seconds: float):
    return boto3.client(
        "bedrock-runtime",
        region_name=region_name,
        config=Config(
            connect_timeout=min(timeout_seconds, 10.0),
            read_timeout=timeout_seconds,
        ),
    )


async def count_tokens_with_bedrock(
    request_data: dict[str, Any],
    model: str,
    aws_region_name: str,
    timeout_seconds: float,
) -> int:
    def _sync() -> int:
        bedrock_runtime_client = get_bedrock_runtime_client(aws_region_name, timeout_seconds)

        # CountTokens API does not support regional model prefixes ("us.anthropic.", "eu.anthropic.")
        count_tokens_model = model.replace("us.anthropic.", "anthropic.").replace("eu.anthropic.", "anthropic.")

        # Build the minimal invoke body Bedrock CountTokens accepts. Unlike invoke_model,
        # CountTokens rejects extra fields such as thinking and tools.
        body = {
            "anthropic_version": BEDROCK_ANTHROPIC_VERSION,
            "max_tokens": request_data.get("max_tokens", DEFAULT_BEDROCK_MAX_TOKENS),
            "messages": request_data.get("messages"),
        }

        response = bedrock_runtime_client.count_tokens(
            modelId=count_tokens_model,
            input={"invokeModel": {"body": json.dumps(body).encode("utf-8")}},
        )
        return int(response["inputTokens"])

    return await asyncio.to_thread(_sync)
