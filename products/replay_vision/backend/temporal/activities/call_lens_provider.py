"""Single Gemini call per lens application; retries once on validation failure with the error fed back."""

import asyncio
from uuid import UUID

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import types
from posthoganalytics.ai.gemini import genai
from pydantic import BaseModel, ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import Team

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.lenses import lens_from_snapshot
from products.replay_vision.backend.temporal.lenses.base import BaseLens
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from products.replay_vision.backend.temporal.types import (
    CallLensProviderInputs,
    LensCallOutput,
    LensLlmInputs,
    LensSnapshot,
)

logger = structlog.get_logger(__name__)

_MAX_LLM_ATTEMPTS = 2  # one initial call + one re-prompt with the validation error appended


@activity.defn
async def call_lens_provider_activity(inputs: CallLensProviderInputs) -> LensCallOutput:
    """Run the lens against the uploaded video + cached events; validate, finalize, return the output."""
    snapshot, team_name, llm_inputs = await asyncio.gather(
        sync_to_async(_load_snapshot)(inputs.observation_id, inputs.team_id),
        sync_to_async(_load_team_name)(inputs.team_id),
        _load_llm_inputs(inputs.observation_id),
    )
    lens = lens_from_snapshot(snapshot)

    prompt_text = lens.build_prompt(team_name=team_name, events=llm_inputs.events)
    prompt_parts: list[types.Part] = [
        types.Part(file_data=types.FileData(file_uri=inputs.file_uri, mime_type=inputs.mime_type)),
        types.Part(text=prompt_text),
    ]

    finalized = await _call_with_retry(
        lens=lens, model=snapshot.model.value, prompt_parts=prompt_parts, team_id=inputs.team_id
    )
    return LensCallOutput(model_output=finalized)


def _load_snapshot(observation_id: UUID, team_id: int) -> LensSnapshot:
    raw = (
        ReplayObservation.objects.filter(pk=observation_id, team_id=team_id)
        .values_list("lens_snapshot", flat=True)
        .first()
    )
    if raw is None:
        raise ApplicationError(f"ReplayObservation {observation_id} not found for team {team_id}", non_retryable=True)
    return LensSnapshot.load_for(observation_id, raw)


def _load_team_name(team_id: int) -> str:
    try:
        return Team.objects.values_list("name", flat=True).get(pk=team_id)
    except Team.DoesNotExist:
        raise ApplicationError(f"Team {team_id} not found", non_retryable=True)


async def _load_llm_inputs(observation_id: UUID) -> LensLlmInputs:
    redis_client, redis_key = get_redis_state_client(
        label=StateActivitiesEnum.SESSION_EVENTS,
        state_id=str(observation_id),
    )
    payload = await get_data_class_from_redis(redis_client, redis_key, target_class=LensLlmInputs)
    if payload is None:
        raise ApplicationError(f"LensLlmInputs missing in Redis for observation {observation_id}", non_retryable=True)
    return payload


async def _call_with_retry(*, lens: BaseLens, model: str, prompt_parts: list[types.Part], team_id: int) -> BaseModel:
    """One Gemini call, plus at most one retry that appends the validation error to the prompt."""
    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    schema_class = lens.llm_response_schema
    response_schema = schema_class.model_json_schema()
    parts = list(prompt_parts)
    last_error: str | None = None

    for attempt in range(_MAX_LLM_ATTEMPTS):
        response = await client.models.generate_content(
            model=f"models/{model}",
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=response_schema,
            ),
            posthog_distinct_id=replay_vision_distinct_id(team_id),
            posthog_groups={"project": str(team_id)},
        )
        response_text = (response.text or "").strip()
        if not response_text:
            last_error = "Empty response from model"
        else:
            try:
                parsed = schema_class.model_validate_json(response_text)
            except ValidationError as e:
                last_error = f"Schema validation failed: {e}"
            else:
                finalized = lens.finalize(parsed)
                semantic_error = lens.validate_semantics(finalized)
                if semantic_error is None:
                    return finalized
                last_error = f"Semantic validation failed: {semantic_error}"

        logger.warning(
            "replay_vision.call_lens_provider.invalid_response",
            attempt=attempt + 1,
            error=last_error,
            response_preview=response_text[:500] if response_text else None,
        )
        if attempt < _MAX_LLM_ATTEMPTS - 1:
            parts = [
                *parts,
                types.Part(
                    text=(
                        f"\n\nYour previous attempt failed: {last_error}\n"
                        "Respond with raw JSON only — no markdown fences, no commentary."
                    )
                ),
            ]

    # `non_retryable=True` so the workflow-level retry doesn't re-burn attempts on schema/semantic failures.
    raise ApplicationError(
        f"Lens call rejected after {_MAX_LLM_ATTEMPTS} attempts: {last_error}",
        non_retryable=True,
    )


__all__ = ["call_lens_provider_activity"]
