"""
LLM calling function for summarization using PostHog's analytics-tracked OpenAI client.

Uses posthoganalytics.ai.openai.AsyncOpenAI for automatic cost tracking and observability.
Follows the same pattern as ee.hogai.session_summaries.llm.call.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
import posthoganalytics
from posthoganalytics.ai.openai import AsyncOpenAI
from rest_framework import exceptions

from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region

from ..constants import SUMMARIZATION_MODEL, SUMMARIZATION_TIMEOUT

if TYPE_CHECKING:
    from .schema import SummarizationResponse

logger = structlog.get_logger(__name__)


def _get_default_posthog_client():
    """Return the default analytics client after validating the environment."""
    if not settings.DEBUG and not is_cloud():
        raise exceptions.ValidationError("AI features are only available in PostHog Cloud")

    if not os.environ.get("OPENAI_API_KEY"):
        raise exceptions.ValidationError("OpenAI API key is not configured")

    client = posthoganalytics.default_client
    if not client:
        raise exceptions.ValidationError("PostHog analytics client is not configured")

    return client


def _get_async_openai_client() -> AsyncOpenAI:
    """Get configured OpenAI client with PostHog analytics tracking."""
    client = _get_default_posthog_client()
    return AsyncOpenAI(
        posthog_client=client,
        timeout=SUMMARIZATION_TIMEOUT,
        base_url=getattr(settings, "OPENAI_BASE_URL", None),
    )


def _prepare_user_param(team_id: int) -> str:
    """Format user identifier for LLM calls."""
    instance_region = get_instance_region() or "HOBBY"
    return f"{instance_region}/{team_id}"


async def summarize(
    text_repr: str,
    team_id: int,
    trace_id: str | None = None,
    mode: str = "minimal",
) -> SummarizationResponse:
    """
    Generate AI-powered summary from text representation.

    Args:
        text_repr: Line-numbered text representation to summarize
        team_id: Team ID for cost tracking and analytics
        trace_id: Optional trace ID for linking LLM call to source trace/event
        mode: Summary detail level ('minimal' or 'detailed')

    Returns:
        Structured summarization response with flow diagram, bullets, and notes
    """
    from ..utils import load_summarization_template
    from .schema import SummarizationResponse

    # Load prompt templates
    system_prompt = load_summarization_template(f"prompts/system_{mode}.djt", {})
    user_prompt = load_summarization_template("prompts/user.djt", {"text_repr": text_repr})

    client = _get_async_openai_client()
    user_param = _prepare_user_param(team_id)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Use structured outputs with JSON schema
    # Pass posthog_trace_id for linking this LLM call to the source trace
    response = await client.chat.completions.create(  # type: ignore[call-overload]
        model=SUMMARIZATION_MODEL,
        messages=messages,
        user=user_param,
        posthog_trace_id=trace_id,
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
