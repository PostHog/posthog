"""
LLM calling function for summarization.

In dev mode, uses direct OpenAI client without PostHog analytics tracking.
In production, can use PostHog-wrapped client for cost tracking if available.
"""

import os

from django.conf import settings

from openai import AsyncOpenAI as DirectAsyncOpenAI
from rest_framework import exceptions

from ..constants import SUMMARIZATION_MODEL, SUMMARIZATION_TIMEOUT
from .schema import SummarizationResponse


def _get_openai_client():
    """
    Get OpenAI client for summarization.

    In dev mode, uses direct OpenAI client without analytics tracking.
    In production, tries PostHog-wrapped client, falls back to direct client.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise exceptions.ValidationError("OpenAI API key is not configured")

    # In dev mode, use direct OpenAI client
    if settings.DEBUG:
        return DirectAsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            timeout=SUMMARIZATION_TIMEOUT,
            base_url=getattr(settings, "OPENAI_BASE_URL", None),
        )

    # In production, try to use PostHog-wrapped client for cost tracking
    try:
        from ee.hogai.session_summaries.llm.call import get_async_openai_client

        return get_async_openai_client()
    except Exception:
        # Fallback to direct client if PostHog client unavailable
        return DirectAsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            timeout=SUMMARIZATION_TIMEOUT,
            base_url=getattr(settings, "OPENAI_BASE_URL", None),
        )


async def call_summarization_llm(system_prompt: str, user_prompt: str) -> SummarizationResponse:
    """
    Call LLM for summarization with structured outputs.

    Args:
        system_prompt: System instructions for the LLM
        user_prompt: User prompt with content to summarize

    Returns:
        Structured summarization response
    """
    client = _get_openai_client()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Use structured outputs with JSON schema
    response = await client.chat.completions.create(
        model=SUMMARIZATION_MODEL,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "summarization_response",
                "strict": True,
                "schema": SummarizationResponse.model_json_schema(),
            },
        },
    )

    # Parse the JSON response into our Pydantic model
    content = response.choices[0].message.content or "{}"
    return SummarizationResponse.model_validate_json(content)
