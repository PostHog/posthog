import os

from django.conf import settings

import structlog
import posthoganalytics
from openai import AsyncStream
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai.types.responses import Response as OpenAIResponse
from posthoganalytics.ai.openai import AsyncOpenAI, OpenAI
from posthoganalytics.client import Client
from rest_framework import exceptions

from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region

from products.enterprise.backend.hogai.session_summaries.constants import (
    BASE_LLM_CALL_TIMEOUT_S,
    SESSION_SUMMARIES_REASONING_EFFORT,
    SESSION_SUMMARIES_SUPPORTED_REASONING_MODELS,
    SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS,
    SESSION_SUMMARIES_TEMPERATURE,
)

logger = structlog.get_logger(__name__)


def _get_default_posthog_client() -> Client:
    """Return the default analytics client after validating the environment."""
    if not settings.DEBUG and not is_cloud():
        raise exceptions.ValidationError("AI features are only available in PostHog Cloud")

    if not os.environ.get("OPENAI_API_KEY"):
        raise exceptions.ValidationError("OpenAI API key is not configured")

    client = posthoganalytics.default_client
    if not client:
        raise exceptions.ValidationError("PostHog analytics client is not configured")

    return client


def get_openai_client() -> OpenAI:
    """Get configured OpenAI client or raise appropriate error."""
    client = _get_default_posthog_client()
    return OpenAI(posthog_client=client, timeout=BASE_LLM_CALL_TIMEOUT_S, base_url=settings.OPENAI_BASE_URL)


def get_async_openai_client() -> AsyncOpenAI:
    """Get configured OpenAI client or raise appropriate error."""
    client = _get_default_posthog_client()
    return AsyncOpenAI(posthog_client=client, timeout=BASE_LLM_CALL_TIMEOUT_S, base_url=settings.OPENAI_BASE_URL)


def _prepare_messages(
    input_prompt: str, session_id: str, assistant_start_text: str | None = None, system_prompt: str | None = None
) -> list[dict[str, str]]:
    """Compose message list for the OpenAI chat API."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if input_prompt:
        messages.append(
            {
                "role": "user",
                "content": input_prompt,
            }
        )
    if assistant_start_text:
        # Force LLM to start with the assistant text
        messages.append({"role": "assistant", "content": assistant_start_text})
    if not messages:
        raise ValueError(f"No messages to send to LLM for sessions: {session_id}")
    return messages


def _prepare_user_param(user_key: int) -> str:
    """Format user identifier for LLM calls."""
    instance_region = get_instance_region() or "HOBBY"
    user_param = f"{instance_region}/{user_key}"
    return user_param


async def stream_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    model: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    trace_id: str | None = None,
) -> AsyncStream[ChatCompletionChunk]:
    """
    LLM streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    client = get_async_openai_client()
    if model not in SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS:
        raise ValueError(
            f"Unsupported model for session summaries: {model} when calling for session id {session_id}. Supported models: "
            f"{SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS}"
        )
    stream: AsyncStream = await client.chat.completions.create(  # type: ignore[call-overload]
        messages=messages,
        model=model,
        temperature=SESSION_SUMMARIES_TEMPERATURE,
        user=user_param,
        stream=True,
        posthog_trace_id=trace_id,
    )
    return stream


async def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    model: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    trace_id: str | None = None,
) -> ChatCompletion | OpenAIResponse:
    """
    LLM non-streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    client = get_async_openai_client()
    if model in SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS:
        result = await client.chat.completions.create(  # type: ignore[call-overload]
            messages=messages,
            model=model,
            temperature=SESSION_SUMMARIES_TEMPERATURE,
            user=user_param,
            posthog_trace_id=trace_id,
        )
    elif model in SESSION_SUMMARIES_SUPPORTED_REASONING_MODELS:
        result = await client.responses.create(  # type: ignore[call-overload]
            input=messages,
            model=model,
            reasoning={"effort": SESSION_SUMMARIES_REASONING_EFFORT},
            user=user_param,
            posthog_trace_id=trace_id,
        )
    else:
        raise ValueError(
            f"Unsupported model for session summaries: {model} when calling for session id {session_id}. Supported models: "
            f"{SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS | SESSION_SUMMARIES_SUPPORTED_REASONING_MODELS}"
        )
    return result
