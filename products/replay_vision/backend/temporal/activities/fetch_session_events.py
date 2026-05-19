from typing import Any

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.temporal.constants import MAX_ACTIVE_SECONDS_FOR_VIDEO_LENS_S
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import EventTable, FetchSessionEventsInputs, LensLlmInputs

# Mirrors session_summary's pagination shape; without it HogQL applies the LimitContext.QUERY default of 100.
_EVENTS_PER_PAGE = 3000
_MAX_EVENT_PAGES = 100


@activity.defn
async def fetch_session_events_activity(inputs: FetchSessionEventsInputs) -> None:
    """Fetch analytics events for a session and stash in Redis; idempotent — a second call finds the key and returns."""
    redis_client, redis_key = get_redis_state_client(
        label=StateActivitiesEnum.SESSION_EVENTS,
        state_id=str(inputs.observation_id),
    )
    if await redis_client.exists(redis_key):
        return

    payload = await sync_to_async(_fetch_payload)(inputs.team_id, inputs.session_id)
    if payload is None:
        raise ApplicationError(
            f"Session {inputs.session_id} has no events to analyze",
            non_retryable=True,
        )

    await store_data_in_redis(redis_client, redis_key, payload.model_dump_json())


def _fetch_payload(team_id: int, session_id: str) -> LensLlmInputs | None:
    team = Team.objects.get(pk=team_id)
    events_obj = SessionReplayEvents()
    metadata = events_obj.get_metadata(session_id=session_id, team=team)
    if metadata is None:
        raise ApplicationError(f"No replay metadata found for session {session_id}", non_retryable=True)
    # `RecordingMetadata` types this as `int` but it can be missing on sparse fixtures; default to 0 to stay below the cap.
    active_seconds = metadata.get("active_seconds") or 0
    if active_seconds > MAX_ACTIVE_SECONDS_FOR_VIDEO_LENS_S:
        raise ApplicationError(
            f"Session {session_id} has {active_seconds}s of active interaction; max is {MAX_ACTIVE_SECONDS_FOR_VIDEO_LENS_S}s",
            non_retryable=True,
        )

    columns: list[str] | None = None
    all_rows: list[list[Any]] = []
    for page in range(_MAX_EVENT_PAGES):
        page_columns, page_rows = events_obj.get_events(
            session_id=session_id,
            team=team,
            metadata=metadata,
            limit=_EVENTS_PER_PAGE,
            page=page,
        )
        if page_columns and columns is None:
            columns = list(page_columns)
        if not page_rows:
            break
        all_rows.extend(list(row) for row in page_rows)
        if len(page_rows) < _EVENTS_PER_PAGE:
            break

    if columns is None or not all_rows:
        return None

    return LensLlmInputs(
        session_id=session_id,
        team_id=team_id,
        session_start_time=metadata["start_time"],
        session_end_time=metadata["end_time"],
        duration_seconds=float(metadata["duration"]),
        events=EventTable(columns=columns, rows=all_rows),
    )
