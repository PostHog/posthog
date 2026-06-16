import json
import time
import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import structlog

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import (
    OBSERVATION_PHASE_INDEX,
    OBSERVATION_PHASE_ORDER,
    ObservationProgress,
)

logger = structlog.get_logger(__name__)

# How often the stream re-reads observation status and re-queries the workflow for progress.
PROGRESS_POLL_INTERVAL_S = 1.5

# Hard cap on how long we hold an ASGI worker for one stream, in case the workflow is stuck or the
# client never disconnects. Observations finish in minutes; well past that we close and free the worker.
MAX_STREAM_DURATION_S = 10 * 60

_TERMINAL_STATUSES = frozenset({ObservationStatus.SUCCEEDED, ObservationStatus.FAILED, ObservationStatus.INELIGIBLE})


def _sse_event(label: str, data: str) -> str:
    return f"event: {label}\ndata: {data}\n\n"


@database_sync_to_async
def _read_observation_state(observation_id: UUID, team_id: int) -> tuple[str, str] | None:
    """Returns (status, workflow_id), or None if the row vanished. Team-scoped: the caller already
    authorized this observation via get_object(), but the query stays tenant-scoped per the IDOR rule."""
    row = (
        ReplayObservation.objects.filter(pk=observation_id, team_id=team_id)
        .values_list("status", "workflow_id")
        .first()
    )
    return None if row is None else (row[0], row[1])


def _fallback_progress(status: str) -> ObservationProgress:
    """Used when the workflow can't be queried yet (brief startup window or post-completion eviction)."""
    phase = "queued" if status == ObservationStatus.PENDING else "fetching"
    return {
        "phase": phase,
        "step": OBSERVATION_PHASE_INDEX[phase],
        "total_steps": len(OBSERVATION_PHASE_ORDER),
        "rasterizer_workflow_id": None,
    }


async def _read_rasterizer_frame_progress(client: Any, rasterizer_workflow_id: str) -> dict[str, Any] | None:
    """Frame counts come from the rasterizer activity's heartbeats. Errors swallowed — progress is best-effort."""
    try:
        child_handle = client.get_workflow_handle(rasterizer_workflow_id)
        desc = await child_handle.describe()
        pending = getattr(desc.raw_description, "pending_activities", None) or []
        if not pending:
            return None
        raw_payloads = list(pending[0].heartbeat_details.payloads)
        if not raw_payloads:
            return None
        codec = getattr(client.data_converter, "payload_codec", None)
        decoded = await codec.decode(raw_payloads) if codec is not None else raw_payloads
        return {"frame_progress": json.loads(decoded[0].data)} if decoded else None
    except Exception:
        return None


async def _query_progress(client: Any, workflow_id: str) -> dict[str, Any] | None:
    """Query the running workflow's `get_progress`; attach rasterizer frame progress while rendering."""
    try:
        payload: dict[str, Any] = await client.get_workflow_handle(workflow_id).query("get_progress")
    except Exception:
        return None  # Workflow not queryable yet/anymore — caller falls back to a status-derived payload.
    rasterizer_workflow_id = payload.get("rasterizer_workflow_id")
    if payload.get("phase") == "rendering" and rasterizer_workflow_id:
        payload["rasterizer"] = await _read_rasterizer_frame_progress(client, rasterizer_workflow_id)
    else:
        payload["rasterizer"] = None
    return payload


async def stream_observation_progress(observation: ReplayObservation) -> AsyncGenerator[str]:
    """SSE generator: live phase + rendering frame progress for one observation until it reaches a terminal state.

    Emits `observation-progress` ticks, then a single `observation-complete` (carrying the terminal status) once the
    row settles; `observation-error` on an unexpected failure. The client refetches the row to render the final result.
    """
    observation_id = observation.id
    team_id = observation.team_id

    # Fast path: already settled (e.g. details page opened after completion) — close immediately.
    if observation.status in _TERMINAL_STATUSES:
        yield _sse_event("observation-complete", json.dumps({"status": observation.status}))
        return

    try:
        client = await async_connect()
    except Exception:
        client = None  # Without Temporal we still tick a status-derived payload so the bar moves.

    deadline = time.monotonic() + MAX_STREAM_DURATION_S
    try:
        while True:
            if time.monotonic() > deadline:
                # Free the ASGI worker rather than hold it open indefinitely on a stuck workflow.
                logger.info("replay_vision.observation_progress_stream_timeout", observation_id=str(observation_id))
                yield _sse_event("observation-error", "Progress stream timed out.")
                return
            state = await _read_observation_state(observation_id, team_id)
            if state is None:
                yield _sse_event("observation-error", "Observation not found")
                return
            status, workflow_id = state
            if status in _TERMINAL_STATUSES:
                yield _sse_event("observation-complete", json.dumps({"status": status}))
                return

            payload = await _query_progress(client, workflow_id) if client and workflow_id else None
            yield _sse_event("observation-progress", json.dumps(payload or _fallback_progress(status)))
            await asyncio.sleep(PROGRESS_POLL_INTERVAL_S)
    except Exception:
        # Don't leak the raw exception (DB hosts, internal details) to the client; it's logged server-side.
        logger.exception("replay_vision.observation_progress_stream_failed", observation_id=str(observation_id))
        yield _sse_event("observation-error", "An unexpected error occurred.")
