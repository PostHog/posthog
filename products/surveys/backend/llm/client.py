"""Gemini client utilities for surveys."""

import uuid
from typing import TypeVar

from django.conf import settings

import structlog
import posthoganalytics
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from pydantic import BaseModel
from rest_framework import exceptions

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def create_gemini_client():
    if settings.DEBUG and posthoganalytics.disabled:
        posthoganalytics.disabled = False
        if not posthoganalytics.host:
            posthoganalytics.host = settings.SITE_URL

    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        logger.warning("PostHog default_client not available, LLM analytics will not be tracked")

    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
        posthog_client=posthog_client,
    )


def generate_structured_output(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_schema: type[T],
    posthog_properties: dict | None = None,
    team_id: int | None = None,
    distinct_id: str | None = None,
) -> tuple[T, str]:
    client = create_gemini_client()

    config = GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_json_schema=response_schema.model_json_schema(),
    )

    trace_id = str(uuid.uuid4())
    properties = posthog_properties or {}

    try:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config,
            posthog_distinct_id=distinct_id or "",
            posthog_trace_id=trace_id,
            posthog_properties=properties,
            posthog_groups={"project": str(team_id)} if team_id else {},
        )

        if not response.text:
            raise exceptions.ValidationError("Gemini returned empty response")

        return response_schema.model_validate_json(response.text), trace_id

    except exceptions.ValidationError:
        raise
    except Exception:
        logger.exception("Gemini API call failed", model=model, properties=properties)
        raise exceptions.APIException("Failed to generate response")
