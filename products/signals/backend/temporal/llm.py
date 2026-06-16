import os
import asyncio
from collections.abc import Callable
from typing import Optional, TypeVar

from django.conf import settings

import anthropic
import structlog
from anthropic.types import MessageParam

from posthog.helpers.tiktoken_encoding import TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model
from posthog.llm.gateway_client import get_async_anthropic_gateway_client

logger = structlog.get_logger(__name__)

MATCHING_MODEL = os.getenv("SIGNAL_MATCHING_LLM_MODEL", "claude-sonnet-4-5")

# Models that support Anthropic extended thinking. Keep in sync with the models we actually use.
ANTHROPIC_THINKING_MODELS = {
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-4-0",
    "claude-opus-4-0",
    "claude-3-7-sonnet-latest",
}
MAX_RETRIES = 3
MAX_RESPONSE_TOKENS = 4096
MAX_QUERY_TOKENS = 2048
TIMEOUT = 100.0

# Transient provider-side failures (returned through the internal LLM gateway) worth retrying
# with backoff. These are deliberately kept distinct from EmptyLLMResponseError and validation
# failures, which are handled separately and must not be masked by an API-level retry.
MAX_API_RETRIES = 3
API_RETRY_BASE_DELAY = 1.0
API_RETRY_MAX_DELAY = 16.0


def _is_retryable_api_error(exc: Exception) -> bool:
    """Whether an Anthropic SDK error is a transient provider blip worth retrying."""
    # Network blips and timeouts (APITimeoutError subclasses APIConnectionError) and 429s.
    if isinstance(exc, anthropic.APIConnectionError | anthropic.RateLimitError):
        return True
    # Any 5xx, including 529 overloaded.
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


async def _create_message_with_retries(client, create_kwargs: dict, retries: int = MAX_API_RETRIES):
    """Call the Anthropic Messages endpoint, retrying transient provider errors with backoff.

    Non-retryable errors (4xx other than 429, auth, bad request) propagate immediately, preserving
    the existing fail-closed behavior for genuinely bad requests.
    """
    last_exception: Exception | None = None
    for attempt in range(retries):
        try:
            return await client.messages.create(**create_kwargs)
        except Exception as e:
            if not _is_retryable_api_error(e) or attempt == retries - 1:
                raise
            delay = min(API_RETRY_BASE_DELAY * (2**attempt), API_RETRY_MAX_DELAY)
            logger.warning(
                f"Transient LLM API error (attempt {attempt + 1}/{retries}), retrying in {delay}s: {e}",
                attempt=attempt + 1,
                retries=retries,
                delay=delay,
            )
            last_exception = e
            await asyncio.sleep(delay)
    # Loop either returns or raises on the final attempt; this is unreachable.
    raise last_exception or RuntimeError("LLM API call failed")


def truncate_query_to_token_limit(query: str, max_tokens: int = MAX_QUERY_TOKENS) -> str:
    """Truncate a query string to fit within token limit for embedding."""
    try:
        enc = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
        tokens = enc.encode(query)
        if len(tokens) <= max_tokens:
            return query
        truncated_tokens = tokens[:max_tokens]
        return enc.decode(truncated_tokens)
    except Exception as e:
        logger.warning(f"Failed to truncate with tiktoken, falling back to char limit: {e}")
        char_limit = max_tokens * 4
        return query[:char_limit]


class EmptyLLMResponseError(Exception):
    """Raised when the LLM returns no text content."""

    pass


def _extract_text_content(response) -> str:
    """Extract text content from Anthropic response."""
    for block in reversed(response.content):
        if block.type == "text":
            return block.text
    raise EmptyLLMResponseError("No text content in response")


# I could not for the life of me get thinking claude to stop outputting markdown.
def _strip_markdown_json_fences(text: str) -> str:
    """Strip ```json ... ``` markdown fences that Claude sometimes wraps around JSON output."""
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        return stripped[len("```json") : -len("```")].strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped[len("```") : -len("```")].strip()
    return text


T = TypeVar("T")


# I reached doing ~the same thing in 3 or 4 places and decided to abstract it.
async def call_llm(
    *,
    team_id: int | None,
    system_prompt: str,
    user_prompt: str,
    validate: Callable[[str], T],
    thinking: bool = False,
    temperature: Optional[float] = 0.2,
    retries: int = MAX_RETRIES,
    stage: Optional[str] = None,
) -> T:
    # Native Anthropic Messages endpoint so prefilling and extended thinking carry over unchanged.
    thinking = thinking and MATCHING_MODEL in ANTHROPIC_THINKING_MODELS
    client = get_async_anthropic_gateway_client(product="signals", team_id=team_id)

    messages: list[MessageParam] = [
        {"role": "user", "content": user_prompt},
    ]

    # For non-thinking calls, pre-fill the assistant response with `{` to prevent markdown fences. Pre-filling seems to work
    # well, but isn't supported for thinking modes.
    if not thinking:
        messages.append({"role": "assistant", "content": "{"})

    create_kwargs: dict = {
        "model": MATCHING_MODEL,
        "system": system_prompt,
        "messages": messages,
        "max_tokens": MAX_RESPONSE_TOKENS,
        "temperature": temperature,
        "timeout": TIMEOUT,
    }
    if team_id is not None:
        create_kwargs["metadata"] = {"user_id": f"team-{team_id}"}
    if stage:
        create_kwargs["extra_headers"] = {"x-posthog-property-ai_stage": stage}

    # Later, we'll want to tune how many tokens we give over to thinking vs. producing output. Hard-coded for now.
    if thinking:
        create_kwargs["max_tokens"] = MAX_RESPONSE_TOKENS * 3
        create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": MAX_RESPONSE_TOKENS * 2}
        create_kwargs["temperature"] = 1  # Required for thinking

    last_exception: Exception | None = None
    for attempt in range(retries):
        response = None
        # NOTE - this outer loop only retries validation failures (see the except below), not
        # extracting text content. Transient API call failures are retried separately, with
        # backoff, inside _create_message_with_retries so a provider blip doesn't fail the call.
        response = await _create_message_with_retries(client, create_kwargs)
        text_content = _extract_text_content(response)
        text_content = _strip_markdown_json_fences(text_content)
        if not thinking:
            # Prepend the `{` we pre-filled
            text_content = "{" + text_content
        try:
            return validate(text_content)
        except Exception as e:
            logger.warning(
                f"LLM call failed (attempt {attempt + 1}/{retries}): {e}",
                attempt=attempt + 1,
                retries=retries,
            )
            # This is expected to contain pretty sensitive and/or large amounts of data, so for real only
            # log it in local dev
            if settings.DEBUG:
                logger.warning(
                    f"LLM response that failed validation:\n{text_content}",
                )
            if response:
                messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response failed validation. Error: {e}\n\nPlease try again with a valid JSON response.",
                }
            )
            # Re-add assistant pre-fill for non-thinking calls so the LLM
            # continues from `{` on the next attempt (matching the prepend above).
            if not thinking:
                messages.append({"role": "assistant", "content": "{"})
            last_exception = e
            continue

    raise last_exception or ValueError(f"LLM call failed after {retries} attempts")
