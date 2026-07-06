from __future__ import annotations

import asyncio
import functools
import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Final

import boto3
import httpx
import structlog
from boto3.session import Session as Boto3Session
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from fastapi import HTTPException

from llm_gateway.config import get_settings
from llm_gateway.metrics.prometheus import BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES

logger = structlog.get_logger(__name__)

BEDROCK_ANTHROPIC_VERSION: Final[str] = "bedrock-2023-05-31"
# The bedrock-mantle endpoint speaks Anthropic's native Messages API, so it expects the
# public Anthropic version string in an HTTP header rather than the bedrock-runtime body value.
BEDROCK_MANTLE_ANTHROPIC_VERSION: Final[str] = "2023-06-01"
BEDROCK_MANTLE_SIGV4_SERVICE: Final[str] = "bedrock-mantle"
DEFAULT_BEDROCK_MAX_TOKENS: Final[int] = 4096
MAX_COUNT_TOKENS_LOSS_REPORT_PATHS: Final[int] = 20
UNSIGNED_THINKING_PROPERTY: Final[str] = "messages.content.thinking_without_signature"
EMPTY_MESSAGE_PROPERTY: Final[str] = "messages.empty_after_sanitization"
COUNT_TOKENS_ROUTING_PROPERTIES: Final[frozenset[str]] = frozenset({"model"})
RUNTIME_COUNT_TOKENS_BODY_PROPERTIES: Final[frozenset[str]] = frozenset({"messages", "max_tokens"})
MANTLE_COUNT_TOKENS_BODY_PROPERTIES: Final[frozenset[str]] = frozenset({"messages", "system", "tool_choice", "tools"})

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
        "us": "us.anthropic.claude-opus-4-7",
        "eu": "eu.anthropic.claude-opus-4-7",
    },
    "claude-opus-4-8": {
        "us": "us.anthropic.claude-opus-4-8",
        "eu": "eu.anthropic.claude-opus-4-8",
    },
    "claude-fable-5": {
        "us": "us.anthropic.claude-fable-5",
        "eu": "eu.anthropic.claude-fable-5",
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
    "claude-sonnet-5": {
        "us": "us.anthropic.claude-sonnet-5",
        "eu": "eu.anthropic.claude-sonnet-5",
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


@functools.lru_cache
def get_bedrock_session() -> Boto3Session:
    return boto3.Session()


def _is_unsigned_thinking_block(block: Any) -> bool:
    """Detect thinking blocks Bedrock CountTokens rejects because they cannot be replay-verified."""
    return isinstance(block, dict) and block.get("type") == "thinking" and not block.get("signature")


@dataclass
class CountTokensSanitizationReport:
    """Bounded record of data lost while adapting an Anthropic CountTokens request."""

    dropped_property_counts: Counter[str] = field(default_factory=Counter)
    dropped_paths: list[str] = field(default_factory=list)
    dropped_items_total: int = 0
    dropped_paths_truncated: bool = False

    def record_drop(self, property_name: str, path: str) -> None:
        """Track a dropped field without storing request contents."""
        self.dropped_property_counts[property_name] += 1
        self.dropped_items_total += 1
        if len(self.dropped_paths) < MAX_COUNT_TOKENS_LOSS_REPORT_PATHS:
            self.dropped_paths.append(path)
        else:
            self.dropped_paths_truncated = True

    @property
    def has_drops(self) -> bool:
        """Return whether this adaptation lost any request data."""
        return self.dropped_items_total > 0


def _sanitize_bedrock_count_tokens_messages(messages: Any) -> tuple[Any, CountTokensSanitizationReport]:
    """Remove nested message content Bedrock CountTokens rejects, preserving a loss report."""
    report = CountTokensSanitizationReport()
    if not isinstance(messages, list):
        return messages, report

    sanitized_messages: list[Any] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        content = message.get("content")
        if not isinstance(content, list):
            sanitized_messages.append(message)
            continue

        sanitized_content: list[Any] = []
        for block_index, block in enumerate(content):
            if _is_unsigned_thinking_block(block):
                report.record_drop(UNSIGNED_THINKING_PROPERTY, f"messages[{message_index}].content[{block_index}]")
                continue
            sanitized_content.append(block)

        if not sanitized_content:
            report.record_drop(EMPTY_MESSAGE_PROPERTY, f"messages[{message_index}]")
            continue

        if len(sanitized_content) == len(content):
            sanitized_messages.append(message)
        else:
            sanitized_messages.append({**message, "content": sanitized_content})

    return sanitized_messages, report


def _record_count_tokens_top_level_drops(
    report: CountTokensSanitizationReport,
    request_data: dict[str, Any],
    *,
    body_properties: frozenset[str],
) -> None:
    """Add omitted top-level request fields to the same loss report as nested drops."""
    for property_name in sorted(request_data):
        if property_name in body_properties or property_name in COUNT_TOKENS_ROUTING_PROPERTIES:
            continue
        report.record_drop(f"top_level.{property_name}", property_name)


def _record_count_tokens_sanitization_report(
    report: CountTokensSanitizationReport,
    *,
    model: str,
    product: str,
    transport: str,
) -> None:
    """Emit one warning and metric update after all CountTokens drops are collected."""
    if not report.has_drops:
        return

    dropped_property_counts = dict(sorted(report.dropped_property_counts.items()))
    for property_name, count in dropped_property_counts.items():
        BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
            transport=transport,
            property=property_name,
            product=product,
        ).inc(count)

    logger.warning(
        "Bedrock CountTokens request sanitized",
        model=model,
        product=product,
        transport=transport,
        dropped_properties=sorted(dropped_property_counts),
        dropped_property_counts=dropped_property_counts,
        dropped_paths=report.dropped_paths,
        dropped_items_total=report.dropped_items_total,
        dropped_paths_truncated=report.dropped_paths_truncated,
    )


async def count_tokens_with_bedrock(
    request_data: dict[str, Any],
    model: str,
    aws_region_name: str,
    timeout_seconds: float,
    *,
    product: str,
) -> int:
    sanitized_messages, report = _sanitize_bedrock_count_tokens_messages(request_data.get("messages"))
    _record_count_tokens_top_level_drops(report, request_data, body_properties=RUNTIME_COUNT_TOKENS_BODY_PROPERTIES)
    _record_count_tokens_sanitization_report(report, model=model, product=product, transport="runtime")

    def _sync() -> int:
        bedrock_runtime_client = get_bedrock_runtime_client(aws_region_name, timeout_seconds)

        # CountTokens API does not support regional model prefixes ("us.anthropic.", "eu.anthropic.")
        count_tokens_model = _strip_regional_inference_prefix(model)

        # Build the minimal invoke body Bedrock CountTokens accepts. Unlike invoke_model,
        # CountTokens rejects extra fields such as thinking and tools.
        body = {
            "anthropic_version": BEDROCK_ANTHROPIC_VERSION,
            "max_tokens": request_data.get("max_tokens", DEFAULT_BEDROCK_MAX_TOKENS),
            "messages": sanitized_messages,
        }

        response = bedrock_runtime_client.count_tokens(
            modelId=count_tokens_model,
            input={"invokeModel": {"body": json.dumps(body).encode("utf-8")}},
        )
        return int(response["inputTokens"])

    return await asyncio.to_thread(_sync)


def _strip_regional_inference_prefix(model: str) -> str:
    """Drop the regional inference-profile prefix ("us.anthropic.", "eu.anthropic.") so the
    bare foundation-model id ("anthropic.<model>") is used for token counting."""
    return model.replace("us.anthropic.", "anthropic.").replace("eu.anthropic.", "anthropic.")


def get_bedrock_mantle_count_tokens_url(region_name: str) -> str:
    return f"https://bedrock-mantle.{region_name}.api.aws/anthropic/v1/messages/count_tokens"


def _sign_bedrock_mantle_request(url: str, body: bytes, region_name: str) -> dict[str, str]:
    """SigV4-sign a bedrock-mantle request using the ambient AWS credentials (same IAM role
    the bedrock-runtime client uses). The AWS SDKs don't expose a client for this endpoint."""
    credentials = get_bedrock_session().get_credentials()
    if credentials is None:
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "AWS credentials not available", "type": "configuration_error"}},
        )

    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": BEDROCK_MANTLE_ANTHROPIC_VERSION,
        },
    )
    SigV4Auth(credentials.get_frozen_credentials(), BEDROCK_MANTLE_SIGV4_SERVICE, region_name).add_auth(request)
    return dict(request.headers)


async def count_tokens_with_bedrock_mantle(
    request_data: dict[str, Any],
    model: str,
    aws_region_name: str,
    timeout_seconds: float,
    *,
    product: str,
) -> int:
    """Count input tokens via Anthropic's count_tokens API on the bedrock-mantle endpoint.

    AWS recommends this path for Claude models that bedrock-runtime CountTokens doesn't support
    (e.g. cross-Region-inference-only models like claude-opus-4-8). Unlike the runtime CountTokens
    body, mantle takes the native Anthropic shape (model + messages + optional system/tools).
    """
    mantle_model = _strip_regional_inference_prefix(model)
    body: dict[str, Any] = {"model": mantle_model, "messages": request_data.get("messages")}
    body["messages"], report = _sanitize_bedrock_count_tokens_messages(body["messages"])
    _record_count_tokens_top_level_drops(report, request_data, body_properties=MANTLE_COUNT_TOKENS_BODY_PROPERTIES)
    _record_count_tokens_sanitization_report(report, model=model, product=product, transport="mantle")
    for key in ("system", "tools", "tool_choice"):
        if key in request_data:
            body[key] = request_data[key]

    payload = json.dumps(body).encode("utf-8")
    url = get_bedrock_mantle_count_tokens_url(aws_region_name)
    # Credential resolution can touch the network (e.g. role refresh), so sign off the event loop.
    headers = await asyncio.to_thread(_sign_bedrock_mantle_request, url, payload, aws_region_name)

    request_start_time = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, content=payload, headers=headers)

    if response.status_code != 200:
        try:
            detail = response.json()
        except Exception:
            detail = {"error": {"message": response.text, "type": "api_error"}}
        raise HTTPException(status_code=response.status_code, detail=detail)

    input_tokens = int(response.json()["input_tokens"])
    logger.info(
        "bedrock-mantle count_tokens request succeeded",
        model=model,
        mantle_model=mantle_model,
        product=product,
        region_name=aws_region_name,
        status_code=response.status_code,
        duration_ms=round((time.monotonic() - request_start_time) * 1000, 2),
    )
    return input_tokens
