"""Run a scanner as a multi-turn, tool-using Gemini conversation over the cached video.

Each scan is a shared preamble plus the scanner's ordered `mission_steps` (one structured turn each). The video
is cached once so the steps don't re-process it; the model pulls analytics events on demand via `get_events_around`.
Each step validates its own output and re-prompts once on failure; required steps abort the scan, best-effort steps
(facets, signals) just contribute nothing.
"""

import re
import time
import asyncio
from typing import Any
from uuid import UUID

import structlog
from asgiref.sync import sync_to_async
from google.genai import (
    Client as GoogleGenAIClient,
    types,
)
from posthoganalytics.ai.gemini import genai
from pydantic import BaseModel, ValidationError
from temporalio import activity

from posthog.models import Team

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.conversation import run_tool_loop
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.events_tool import dispatch_events_tool, events_tool
from products.replay_vision.backend.temporal.gemini import gemini_api_key
from products.replay_vision.backend.temporal.metrics import REPLAY_VISION_PROVIDER_CALL
from products.replay_vision.backend.temporal.scanners import scanner_from_snapshot
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    ChipSegment,
    MissionStep,
    Segment,
    SignalFinding,
    TextSegment,
)
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

_MAX_LLM_ATTEMPTS = 2  # one initial call + one re-prompt with the validation error appended per step
# Cache TTL: a scan is a handful of turns and finishes in minutes; well under this.
_VIDEO_CACHE_TTL = "900s"
# `(t <seconds>)` with optional leading whitespace, so we eat the space when stripping the paren.
_TIMESTAMP_CITATION_RE = re.compile(r"\s*\(t (\d+)\)")


@activity.defn
@track_activity()
async def call_scanner_provider_activity(inputs: CallScannerProviderInputs) -> ScannerCallOutput:
    """Run the scanner conversation against the uploaded video + cached events; validate, finalize, return the output."""
    snapshot, team_name, llm_inputs = await asyncio.gather(
        sync_to_async(_load_snapshot)(inputs.observation_id, inputs.team_id),
        sync_to_async(_load_team_name)(inputs.team_id),
        _load_llm_inputs(inputs.observation_id),
    )
    scanner = scanner_from_snapshot(snapshot)

    preamble_text = scanner.preamble(team_name=team_name, session_metadata=llm_inputs.metadata.as_prompt_dict())
    video_part = types.Part(file_data=types.FileData(file_uri=inputs.file_uri, mime_type=inputs.mime_type))

    finalized, signals = await _run_mission(
        scanner=scanner,
        snapshot=snapshot,
        video_part=video_part,
        preamble_text=preamble_text,
        team_id=inputs.team_id,
        llm_inputs=llm_inputs,
    )
    duration_ms = int(llm_inputs.metadata.duration_seconds * 1000)
    finalized = _resolve_citations(finalized, scanner, duration_ms)
    return ScannerCallOutput(model_output=finalized, signals=signals)


def _resolve_citations(
    finalized: BaseModel,
    scanner: BaseScanner,
    duration_ms: int,
) -> BaseModel:
    """Walk each `(t <sec>)` marker in the citation fields: drop out-of-range ones, build the plain text, and persist a parallel render-ready segment list."""
    field_updates: dict[str, str | list[Segment]] = {}
    for field in scanner.citation_fields:
        text = getattr(finalized, field, None)
        if not isinstance(text, str):
            continue
        plain, segments = _extract_segments(text, duration_ms)
        field_updates[field] = plain
        field_updates[f"{field}_segments"] = segments

    if field_updates:
        finalized = finalized.model_copy(update=field_updates)
    return finalized


def _extract_segments(text: str, duration_ms: int) -> tuple[str, list[Segment]]:
    """Walk `(t <sec>)` markers in `text`; drop times past the recording; return (plain text, render-ready text/chip segments)."""
    plain_parts: list[str] = []
    segments: list[Segment] = []
    last_end = 0
    for match in _TIMESTAMP_CITATION_RE.finditer(text):
        chunk = text[last_end : match.start()]
        plain_parts.append(chunk)
        if chunk:
            segments.append(TextSegment(value=chunk))
        timestamp_ms = int(match.group(1)) * 1000
        # Drop citations past the recording end (a misread footer value); the marker is stripped either way.
        if timestamp_ms <= duration_ms:
            segments.append(ChipSegment(timestamp_ms=timestamp_ms))
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


async def _run_mission(
    *,
    scanner: BaseScanner,
    snapshot: ScannerSnapshot,
    video_part: types.Part,
    preamble_text: str,
    team_id: int,
    llm_inputs: ScannerLlmInputs,
) -> tuple[BaseScannerOutput, list[SignalFinding]]:
    """Cache the video, run every mission step as a tool-using turn, then assemble the output + side-mission findings.

    Caching is best-effort: a video too short to cache (or any cache hiccup) falls back to sending it inline, and a
    cached run that fails for a non-validation reason is retried inline once before giving up.
    """
    client = genai.AsyncClient(api_key=gemini_api_key())
    cache_client = GoogleGenAIClient(api_key=gemini_api_key())
    model = f"models/{snapshot.model.value}"
    steps = scanner.mission_steps()
    metric_labels = {
        "provider": snapshot.provider.value,
        "model": snapshot.model.value,
        "scanner_type": snapshot.scanner_type.value,
    }

    def dispatch(call: Any) -> dict[str, Any]:
        return dispatch_events_tool(call, llm_inputs)

    cache = await _maybe_create_video_cache(cache_client, model, video_part, preamble_text)
    try:
        try:
            step_outputs = await _run_steps(
                client=client,
                model=model,
                steps=steps,
                video_part=video_part,
                preamble_text=preamble_text,
                cache_name=cache.name if cache else None,
                dispatch=dispatch,
                team_id=team_id,
                metric_labels=metric_labels,
            )
        except ScannerFailureError:
            raise  # a required step genuinely couldn't be satisfied — re-running won't help.
        except Exception:
            if cache is None:
                raise
            logger.warning("replay_vision.video_cache.run_failed_retrying_inline", model=snapshot.model.value)
            step_outputs = await _run_steps(
                client=client,
                model=model,
                steps=steps,
                video_part=video_part,
                preamble_text=preamble_text,
                cache_name=None,
                dispatch=dispatch,
                team_id=team_id,
                metric_labels=metric_labels,
            )
    finally:
        if cache is not None:
            await _delete_video_cache(cache_client, cache.name)

    return scanner.assemble(step_outputs)


async def _run_steps(
    *,
    client: Any,
    model: str,
    steps: list[MissionStep],
    video_part: types.Part,
    preamble_text: str,
    cache_name: str | None,
    dispatch: Any,
    team_id: int,
    metric_labels: dict[str, str],
) -> dict[str, BaseModel]:
    """Run the ordered steps over one growing conversation; return the validated output keyed by step name."""
    # The video + preamble lead the conversation inline unless they're already cached as the prefix.
    convo: list[Any] = [] if cache_name else [video_part, types.Part(text=preamble_text)]
    step_outputs: dict[str, BaseModel] = {}
    for step in steps:
        convo.append(types.Part(text=step.instruction))
        parsed = await _run_step(
            client=client,
            model=model,
            step=step,
            convo=convo,
            cache_name=cache_name,
            dispatch=dispatch,
            team_id=team_id,
            metric_labels=metric_labels,
        )
        if parsed is None:
            if step.required:
                raise ScannerFailureError(
                    f"Required step '{step.name}' rejected after {_MAX_LLM_ATTEMPTS} attempts",
                    kind=FailureKind.VALIDATION_FAILED,
                )
            continue
        step_outputs[step.name] = parsed
    return step_outputs


async def _run_step(
    *,
    client: Any,
    model: str,
    step: MissionStep,
    convo: list[Any],
    cache_name: str | None,
    dispatch: Any,
    team_id: int,
    metric_labels: dict[str, str],
) -> BaseModel | None:
    """Run one step's tool loop with one re-prompt on failure. Returns the validated output, or None when exhausted.

    On success the model's answer is appended to `convo` so the next step sees it; on failure a correction is
    appended and we retry.
    """
    config = _step_config(step, cache_name)

    async def _generate(c: list[Any]) -> Any:
        return await client.models.generate_content(
            model=model,
            contents=c,
            config=config,
            posthog_distinct_id=replay_vision_distinct_id(team_id),
            posthog_groups={"project": str(team_id)},
        )

    last_error: str | None = None
    for attempt in range(_MAX_LLM_ATTEMPTS):
        started = time.monotonic()
        try:
            response = await run_tool_loop(generate=_generate, convo=convo, dispatch=dispatch)
        except Exception:
            REPLAY_VISION_PROVIDER_CALL.labels(**metric_labels, outcome="provider_error").observe(
                time.monotonic() - started
            )
            raise

        text = (response.text or "").strip()
        parsed, error = _parse_and_validate(step, text)
        REPLAY_VISION_PROVIDER_CALL.labels(
            **metric_labels, outcome="ok" if error is None else "validation_failed"
        ).observe(time.monotonic() - started)

        if error is None:
            convo.append(response.candidates[0].content)  # carry the answer into the next turn
            return parsed

        last_error = error
        logger.warning(
            "replay_vision.call_scanner_provider.invalid_response",
            step=step.name,
            attempt=attempt + 1,
            error=last_error,
            response_preview=text[:500] if text else None,
        )
        if attempt < _MAX_LLM_ATTEMPTS - 1:
            convo.append(
                types.Part(
                    text=(
                        f"\n\nYour previous attempt failed: {last_error}\n"
                        "Respond with raw JSON only — no markdown fences, no commentary."
                    )
                )
            )

    logger.warning(
        "replay_vision.call_scanner_provider.step_exhausted",
        step=step.name,
        required=step.required,
        error=last_error,
    )
    return None


def _step_config(step: MissionStep, cache_name: str | None) -> types.GenerateContentConfig:
    """Generation config for one step: its JSON schema, plus the events tool (from the cache when cached)."""
    kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_json_schema": step.response_model.model_json_schema(),
    }
    if cache_name:
        kwargs["cached_content"] = cache_name  # video, preamble, and the tool all live in the cache
    else:
        kwargs["tools"] = [events_tool()]
    return types.GenerateContentConfig(**kwargs)


def _parse_and_validate(step: MissionStep, text: str) -> tuple[BaseModel | None, str | None]:
    """Parse `text` against the step schema and run its semantic check; return (parsed, None) or (None, error)."""
    if not text:
        return None, "Empty response from model"
    try:
        parsed = step.response_model.model_validate_json(text)
    except ValidationError as e:
        return None, f"Schema validation failed: {e}"
    if step.validate is not None:
        semantic_error = step.validate(parsed)
        if semantic_error is not None:
            return None, f"Semantic validation failed: {semantic_error}"
    return parsed, None


async def _maybe_create_video_cache(
    cache_client: GoogleGenAIClient,
    model: str,
    video_part: types.Part,
    preamble_text: str,
) -> Any | None:
    """Cache the video + preamble + events tool once so the steps reuse them. None on any failure (e.g. too short to cache)."""
    try:
        return await cache_client.aio.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                contents=[types.Content(role="user", parts=[video_part, types.Part(text=preamble_text)])],
                tools=[events_tool()],
                ttl=_VIDEO_CACHE_TTL,
            ),
        )
    except Exception as e:
        logger.info("replay_vision.video_cache.skipped", error=str(e))
        return None


async def _delete_video_cache(cache_client: GoogleGenAIClient, name: str) -> None:
    try:
        await cache_client.aio.caches.delete(name=name)
    except Exception as e:
        # TTL reaps it regardless; a delete failure is not worth surfacing.
        logger.info("replay_vision.video_cache.delete_failed", error=str(e))


__all__ = ["call_scanner_provider_activity"]
