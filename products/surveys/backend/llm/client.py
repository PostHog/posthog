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

from posthog.event_usage import groups
from posthog.llm.gateway_client import build_gemini_client, resolve_ai_gateway_config

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

AI_PRODUCT = "surveys"


def gemini_configured() -> bool:
    return bool(settings.GEMINI_API_KEY) or resolve_ai_gateway_config() is not None


def create_gemini_client():
    if settings.DEBUG and posthoganalytics.disabled:
        posthoganalytics.disabled = False
        if not posthoganalytics.host:
            posthoganalytics.host = settings.SITE_URL

    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        logger.warning("PostHog default_client not available, AI observability will not be tracked")

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
    billable: bool = False,
) -> tuple[T, str]:
    config = GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_json_schema=response_schema.model_json_schema(),
    )

    trace_id = str(uuid.uuid4())
    properties = {**(posthog_properties or {})}
    posthog_groups = {"project": str(team_id)} if team_id else {}
    if billable and team_id is not None:
        properties["team_id"] = team_id
        properties["$ai_billable"] = True
        posthog_groups.update(groups())

    try:
        gateway_client = build_gemini_client(
            ai_product=AI_PRODUCT,
            trace_id=trace_id,
            properties=_gateway_labels(properties, team_id),
            distinct_id=distinct_id,
        )
        if gateway_client:
            response = gateway_client.models.generate_content(model=model, contents=user_prompt, config=config)
        else:
            response = create_gemini_client().models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
                posthog_distinct_id=distinct_id or "",
                posthog_trace_id=trace_id,
                posthog_properties=properties,
                posthog_groups=posthog_groups,
            )

        if not response.text:
            raise exceptions.ValidationError("Gemini returned empty response")

        return response_schema.model_validate_json(response.text), trace_id

    except exceptions.ValidationError:
        raise
    except Exception:
        logger.exception("Gemini API call failed", model=model, properties=properties)
        raise exceptions.APIException("Failed to generate response")


def _gateway_labels(properties: dict, team_id: int | None) -> dict[str, str]:
    labels = {
        key: str(value)
        for key, value in properties.items()
        if value is not None and key != "ai_product" and not key.startswith("$")
    }
    if team_id is not None:
        labels["team_id"] = str(team_id)
    return labels
