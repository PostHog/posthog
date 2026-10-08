"""Asks the model for a structured answer through the PostHog AI gateway."""

from __future__ import annotations

import base64
from typing import Any, TypeVar

import structlog
from anthropic import APIError
from pydantic import BaseModel

from posthog.llm.gateway_client import GatewayNotConfiguredError, build_anthropic_client

logger = structlog.get_logger(__name__)

MODEL = "claude-opus-5"
AI_PRODUCT = "metrics_suggested_dashboards"
MAX_TOKENS = 16000

AnswerT = TypeVar("AnswerT", bound=BaseModel)


class ModelUnavailable(Exception):
    """No gateway is configured, so no AI step can run here. The caller falls back or stops."""


class ModelFailed(Exception):
    """The call went out and failed, or the answer did not fit the schema."""


def image_block(png: bytes) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()},
    }


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def ask_model(
    *, team_id: int, stage: str, system: str, content: list[dict[str, Any]], answer_type: type[AnswerT]
) -> AnswerT:
    try:
        client = build_anthropic_client(
            product="django", ai_product=AI_PRODUCT, team_id=team_id, properties={"ai_stage": stage}
        )
    except GatewayNotConfiguredError as error:
        raise ModelUnavailable(str(error)) from error
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
            output_format=answer_type,
        )
    except APIError as error:
        logger.warning("metrics_suggested_dashboards_model_failed", stage=stage, team_id=team_id, error=str(error))
        raise ModelFailed(f"The model call failed: {error.__class__.__name__}") from error
    if response.stop_reason == "refusal":
        raise ModelFailed("The model declined to answer.")
    answer = response.parsed_output
    if answer is None:
        raise ModelFailed(f"The model answer did not fit the schema (stop reason {response.stop_reason}).")
    return answer
