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


class _NoOpPostHogClient:
    """
    A no-op PostHog client that doesn't track events.

    Used to disable tracking for LLM summarization calls to avoid noise in the central
    PostHog project. The AsyncOpenAI wrapper checks for the presence of a 'capture'
    method before tracking, so by not implementing it, we disable tracking entirely.

    TODO: Re-evaluate this decision after v1. We may want to track summarization LLM
    calls separately or with specific properties to distinguish them from other AI usage.
    """

    privacy_mode = False


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
    """
    Get configured OpenAI client with PostHog analytics tracking disabled.

    We use a no-op client to disable tracking for v1 to avoid adding noise to the
    central PostHog project, which already tracks all PostHog AI usage.
    """
    # Validate environment but don't use the client for tracking
    _get_default_posthog_client()

    # Use no-op client to disable tracking
    return AsyncOpenAI(
        posthog_client=_NoOpPostHogClient(),  # type: ignore[arg-type]
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
    mode: str = "minimal",
    model: str | None = None,
) -> SummarizationResponse:
    """
    Generate AI-powered summary from text representation.

    Args:
        text_repr: Line-numbered text representation to summarize
        team_id: Team ID for cost tracking and analytics
        mode: Summary detail level ('minimal' or 'detailed')
        model: LLM model to use (defaults to SUMMARIZATION_MODEL constant)

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

    # Use provided model or fall back to default
    model_to_use = model or SUMMARIZATION_MODEL

    # Use structured outputs with JSON schema
    # Note: We intentionally do NOT pass posthog_trace_id to avoid the summarization
    # LLM call appearing as part of the trace being summarized (which would create
    # recursive/confusing trace hierarchies). The LLM call is still tracked to the
    # central PostHog project for cost monitoring, just as a separate trace.
    try:
        response = await client.chat.completions.create(  # type: ignore[call-overload]
            model=model_to_use,
            messages=messages,
            user=user_param,
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
        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return SummarizationResponse.model_validate_json(content)
    except Exception as e:
        error_msg = str(e)
        logger.exception("OpenAI API call failed", error=error_msg, team_id=team_id)
        raise exceptions.APIException(f"Failed to generate summary: {error_msg}")
