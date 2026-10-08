import json
import time
from typing import Any, Literal

from django.conf import settings

import httpx
import structlog
from anthropic import Anthropic, AnthropicError, APIConnectionError, InternalServerError, RateLimitError
from anthropic.types import OutputConfigParam

from posthog.llm.gateway_client import build_ai_gateway_anthropic_client, team_distinct_id

logger = structlog.get_logger(__name__)

CONTENT_AUTOPILOT_AI_PRODUCT = "web_analytics"
DEFAULT_TIMEOUT_SECONDS = 300.0
RETRY_DELAYS_SECONDS = (2.0, 8.0)
TRANSIENT_ERRORS = (httpx.HTTPError, APIConnectionError, InternalServerError, RateLimitError)
UNREACHABLE_MESSAGE = "The AI model couldn't finish this draft. Regenerate to try again."
UNREADABLE_MESSAGE = "The AI model sent back a draft PostHog couldn't read. Regenerate to try again."
TIMED_OUT_MESSAGE = "The AI model took too long to respond. Regenerate to try again."


class ContentAutopilotLLMError(Exception):
    pass


def build_client(*, team_id: int, properties: dict[str, str]) -> Anthropic:
    try:
        return build_ai_gateway_anthropic_client(
            ai_product=CONTENT_AUTOPILOT_AI_PRODUCT,
            properties={**properties, "source_product": "content_autopilot"},
            distinct_id=team_distinct_id(team_id),
            team_id=team_id,
        )
    except ValueError as error:
        raise ContentAutopilotLLMError("The AI gateway is not configured.") from error


Effort = Literal["low", "medium", "high"]


def _output_config(schema: dict[str, Any], effort: Effort | None) -> OutputConfigParam:
    config: OutputConfigParam = {"format": {"type": "json_schema", "schema": schema}}
    if effort is not None:
        config["effort"] = effort
    return config


def call_json(
    client: Anthropic,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int,
    team_id: int,
    model: str | None = None,
    effort: Effort | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None)):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ContentAutopilotLLMError(TIMED_OUT_MESSAGE)
        try:
            return _call_json_once(
                client,
                system=system,
                user=user,
                schema=schema,
                max_tokens=max_tokens,
                team_id=team_id,
                model=model,
                effort=effort,
                timeout_seconds=remaining,
            )
        except TRANSIENT_ERRORS as error:
            if delay is None or time.monotonic() + delay >= deadline:
                logger.warning("content_autopilot_llm_failed", team_id=team_id, error=type(error).__name__)
                raise ContentAutopilotLLMError(UNREACHABLE_MESSAGE) from error
            logger.warning(
                "content_autopilot_llm_retry", team_id=team_id, attempt=attempt + 1, error=type(error).__name__
            )
            time.sleep(delay)
        except AnthropicError as error:
            logger.warning("content_autopilot_llm_failed", team_id=team_id, error=type(error).__name__)
            raise ContentAutopilotLLMError(UNREACHABLE_MESSAGE) from error
    raise ContentAutopilotLLMError(UNREACHABLE_MESSAGE)


def _call_json_once(
    client: Anthropic,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int,
    team_id: int,
    model: str | None,
    effort: Effort | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    content: list[str] = []
    stop_reason: str | None = None
    stream = client.with_options(max_retries=0).messages.create(
        model=model or settings.CONTENT_AUTOPILOT_MODEL,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config=_output_config(schema, effort),
        max_tokens=max_tokens,
        metadata={"user_id": team_distinct_id(team_id)},
        stream=True,
        timeout=timeout_seconds,
    )
    try:
        for event in stream:
            if time.monotonic() >= deadline:
                raise ContentAutopilotLLMError(TIMED_OUT_MESSAGE)
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                content.append(event.delta.text)
            elif event.type == "message_delta" and event.delta.stop_reason:
                stop_reason = event.delta.stop_reason
    finally:
        stream.close()

    if stop_reason == "max_tokens":
        raise ContentAutopilotLLMError("The draft ran longer than the AI model allows. Regenerate to try again.")
    try:
        parsed = json.loads("".join(content))
    except json.JSONDecodeError as error:
        raise ContentAutopilotLLMError(UNREADABLE_MESSAGE) from error
    if not isinstance(parsed, dict):
        raise ContentAutopilotLLMError(UNREADABLE_MESSAGE)
    return parsed
