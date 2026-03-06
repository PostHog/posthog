import os
from collections.abc import Callable
from typing import Optional, TypeVar

from django.conf import settings

import tiktoken
import structlog
import posthoganalytics
from anthropic.types import MessageParam
from posthoganalytics.ai.anthropic import AsyncAnthropic

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


def get_async_anthropic_client() -> AsyncAnthropic:
    """Get configured AsyncAnthropic client with PostHog analytics."""
    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        raise ValueError("PostHog analytics client not configured")

    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    return AsyncAnthropic(
        api_key=api_key,
        posthog_client=posthog_client,
        timeout=TIMEOUT,
    )


def truncate_query_to_token_limit(query: str, max_tokens: int = MAX_QUERY_TOKENS) -> str:
    """Truncate a query string to fit within token limit for embedding."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(query)
        if len(tokens) <= max_tokens:
            return query
        truncated_tokens = tokens[:max_tokens]
        return enc.decode(truncated_tokens)
    except Exception as e:
        logger.warning(f"Failed to truncate with tiktoken, falling back to char limit: {e}")
        char_limit = max_tokens * 4
        return query[:char_limit]


def _extract_text_content(response) -> str:
    """Extract text content from Anthropic response."""
    for block in reversed(response.content):
        if block.type == "text":
            return block.text
    raise ValueError("No text content in response")


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
    system_prompt: str,
    user_prompt: str,
    validate: Callable[[str], T],
    thinking: bool = False,
    temperature: Optional[float] = 0.2,
    retries: int = MAX_RETRIES,
) -> T:
    # Worth noting a lot of this code only really works for the Anthropic API, I think (prefilling and thinking in particular). Haven't
    # looked into the OpenAI SDK yet - that'll be for the switch to the LLM gateway.
    thinking = thinking and MATCHING_MODEL in ANTHROPIC_THINKING_MODELS
    client = get_async_anthropic_client()

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
    }

    # Later, we'll want to tune how many tokens we give over to thinking vs. producing output. Hard-coded for now.
    if thinking:
        create_kwargs["max_tokens"] = MAX_RESPONSE_TOKENS * 3
        create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": MAX_RESPONSE_TOKENS * 2}
        create_kwargs["temperature"] = 1  # Required for thinking

    last_exception: Exception | None = None
    for attempt in range(retries):
        response = None
        # NOTE - we explicitly don't want to retry if we fail to call the llm, or fail to extract text content,
        # only if we fail to validate the response.
        response = await client.messages.create(**create_kwargs)
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
