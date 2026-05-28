"""Single Gemini call per scanner application; retries once on validation failure with the error fed back."""

import re
import time
import asyncio
from uuid import UUID

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import types
from posthoganalytics.ai.gemini import genai
from pydantic import BaseModel, ValidationError
from temporalio import activity

from posthog.models import Team

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.metrics import REPLAY_VISION_PROVIDER_CALL
from products.replay_vision.backend.temporal.scanners import scanner_from_snapshot
from products.replay_vision.backend.temporal.scanners.base import BaseScanner, ChipSegment, Segment, TextSegment
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from products.replay_vision.backend.temporal.types import (
    CallScannerProviderInputs,
    ScannerCallOutput,
    ScannerLlmInputs,
    ScannerSnapshot,
)

logger = structlog.get_logger(__name__)

_MAX_LLM_ATTEMPTS = 2  # one initial call + one re-prompt with the validation error appended
# `(event_uuid <uuid>)` with optional leading whitespace, so we eat the space when stripping the paren.
_EVENT_UUID_CITATION_RE = re.compile(
    r"\s*\(event_uuid ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)",
    re.IGNORECASE,
)


@activity.defn
@track_activity()
async def call_scanner_provider_activity(inputs: CallScannerProviderInputs) -> ScannerCallOutput:
    """Run the scanner against the uploaded video + cached events; validate, finalize, return the output."""
    snapshot, team_name, llm_inputs = await asyncio.gather(
        sync_to_async(_load_snapshot)(inputs.observation_id, inputs.team_id),
        sync_to_async(_load_team_name)(inputs.team_id),
        _load_llm_inputs(inputs.observation_id),
    )
    scanner = scanner_from_snapshot(snapshot)

    prompt_text = scanner.build_prompt(
        team_name=team_name,
        events=llm_inputs.events,
        url_mapping=llm_inputs.url_mapping,
        window_mapping=llm_inputs.window_mapping,
        session_metadata=llm_inputs.metadata.as_prompt_dict(),
    )
    prompt_parts: list[types.Part] = [
        types.Part(file_data=types.FileData(file_uri=inputs.file_uri, mime_type=inputs.mime_type)),
        types.Part(text=prompt_text),
    ]

    finalized = await _call_with_retry(
        scanner=scanner,
        snapshot=snapshot,
        prompt_parts=prompt_parts,
        team_id=inputs.team_id,
    )
    finalized = _resolve_citations(finalized, scanner, llm_inputs.event_timestamps)
    return ScannerCallOutput(model_output=finalized)


def _resolve_citations(
    finalized: BaseModel,
    scanner: BaseScanner,
    event_timestamps: dict[str, int],
) -> BaseModel:
    """Walk each `(event_uuid <uuid>)` marker in the citation fields: drop hallucinated ones, build the plain text, and persist a parallel render-ready segment list."""
    field_updates: dict[str, str | list[Segment]] = {}
    for field in scanner.citation_fields:
        text = getattr(finalized, field, None)
        if not isinstance(text, str):
            continue
        plain, segments = _extract_segments(text, event_timestamps)
        field_updates[field] = plain
        field_updates[f"{field}_segments"] = segments

    if field_updates:
        finalized = finalized.model_copy(update=field_updates)
    return finalized


def _extract_segments(text: str, event_timestamps: dict[str, int]) -> tuple[str, list[Segment]]:
    """Walk `(event_uuid <uuid>)` markers in `text`; drop hallucinated uuids; return (plain text, render-ready text/chip segments)."""
    # The vast majority of fields have no citations; skip the regex pass entirely on those.
    if "(event_uuid " not in text:
        return text, [TextSegment(value=text)] if text else []
    plain_parts: list[str] = []
    segments: list[Segment] = []
    last_end = 0
    for match in _EVENT_UUID_CITATION_RE.finditer(text):
        chunk = text[last_end : match.start()]
        plain_parts.append(chunk)
        if chunk:
            segments.append(TextSegment(value=chunk))
        uuid = match.group(1).lower()
        timestamp_ms = event_timestamps.get(uuid)
        if timestamp_ms is not None:
            segments.append(ChipSegment(uuid=uuid, timestamp_ms=timestamp_ms))
        last_end = match.end()
    trailing = text[last_end:]
    plain_parts.append(trailing)
    if trailing:
        segments.append(TextSegment(value=trailing))
    return "".join(plain_parts), segments


def _load_snapshot(observation_id: UUID, team_id: int) -> ScannerSnapshot:
    raw = (
        ReplayObservation.objects.filter(pk=observation_id, team_id=team_id)
        .values_list("scanner_snapshot", flat=True)
        .first()
    )
    if raw is None:
        raise ScannerFailureError(
            f"ReplayObservation {observation_id} not found for team {team_id}", kind=FailureKind.INTERNAL_ERROR
        )
    return ScannerSnapshot.load_for(observation_id, raw)


def _load_team_name(team_id: int) -> str:
    try:
        return Team.objects.values_list("name", flat=True).get(pk=team_id)
    except Team.DoesNotExist:
        raise ScannerFailureError(f"Team {team_id} not found", kind=FailureKind.INTERNAL_ERROR)


async def _load_llm_inputs(observation_id: UUID) -> ScannerLlmInputs:
    redis_client, redis_key = get_redis_state_client(
        label=StateActivitiesEnum.SESSION_EVENTS,
        state_id=str(observation_id),
    )
    payload = await get_data_class_from_redis(redis_client, redis_key, target_class=ScannerLlmInputs)
    if payload is None:
        raise ScannerFailureError(
            f"ScannerLlmInputs missing in Redis for observation {observation_id}", kind=FailureKind.INTERNAL_ERROR
        )
    return payload


async def _call_with_retry(
    *, scanner: BaseScanner, snapshot: ScannerSnapshot, prompt_parts: list[types.Part], team_id: int
) -> BaseModel:
    """One Gemini call, plus at most one retry that appends the validation error to the prompt."""
    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    schema_class = scanner.llm_response_schema
    response_schema = schema_class.model_json_schema()
    parts = list(prompt_parts)
    last_error: str | None = None
    metric_labels = {
        "provider": snapshot.provider.value,
        "model": snapshot.model.value,
        "scanner_type": snapshot.scanner_type.value,
    }

    for attempt in range(_MAX_LLM_ATTEMPTS):
        started = time.monotonic()
        outcome = "provider_error"
        try:
            response = await client.models.generate_content(
                model=f"models/{snapshot.model.value}",
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=response_schema,
                ),
                posthog_distinct_id=replay_vision_distinct_id(team_id),
                posthog_groups={"project": str(team_id)},
            )
        except Exception:
            REPLAY_VISION_PROVIDER_CALL.labels(**metric_labels, outcome=outcome).observe(time.monotonic() - started)
            raise
        response_text = (response.text or "").strip()
        if not response_text:
            last_error = "Empty response from model"
            outcome = "validation_failed"
        else:
            try:
                parsed = schema_class.model_validate_json(response_text)
            except ValidationError as e:
                last_error = f"Schema validation failed: {e}"
                outcome = "validation_failed"
            else:
                finalized = scanner.finalize(parsed)
                semantic_error = scanner.validate_semantics(finalized)
                if semantic_error is None:
                    REPLAY_VISION_PROVIDER_CALL.labels(**metric_labels, outcome="ok").observe(
                        time.monotonic() - started
                    )
                    return finalized
                last_error = f"Semantic validation failed: {semantic_error}"
                outcome = "validation_failed"
        REPLAY_VISION_PROVIDER_CALL.labels(**metric_labels, outcome=outcome).observe(time.monotonic() - started)

        logger.warning(
            "replay_vision.call_scanner_provider.invalid_response",
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

    # non_retryable so workflow-level retries don't re-burn on schema/semantic failures.
    raise ScannerFailureError(
        f"Scanner call rejected after {_MAX_LLM_ATTEMPTS} attempts: {last_error}",
        kind=FailureKind.VALIDATION_FAILED,
    )


__all__ = ["call_scanner_provider_activity"]
