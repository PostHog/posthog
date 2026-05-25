import hashlib
import datetime as dt
from typing import Any

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.temporal.constants import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import (
    EventCitation,
    EventTable,
    FetchSessionEventsInputs,
    ScannerLlmInputs,
    SessionMetadata,
)

# Pagination shape mirrors session_summary's fetcher; without it HogQL applies LimitContext.QUERY's default of 100.
_EVENTS_PER_PAGE = 3000
_MAX_EVENT_PAGES = 5  # Hard cap on prompt size for very chatty sessions; sets `events_truncated` when reached.

# Noisy SDK-internal events that add no signal for the LLM.
_EVENTS_TO_IGNORE = ["$feature_flag_called"]

# `properties.*` is the HogQL prefix for JSON properties; bare names are top-level columns.
# `uuid` lets us map short event_ids back to real events; never sent to the LLM.
_EXTRA_FIELDS = [
    "uuid",
    "elements_chain_ids",
    "properties.$exception_types",
    "properties.$exception_values",
]

# Token names for URL and window-id simplification — referenced by `base.jinja`'s resolver instructions.
_URL_PREFIX = "url"
_WINDOW_PREFIX = "window"
# Per-value cap to keep one oversized field from blowing the prompt token budget.
_MAX_FIELD_LEN = 2000
# 64-bit hex hash for event dedup — 32-bit (8 hex) hits 50% birthday-collision around 77k events.
_EVENT_ID_BYTES = 8


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


def _fetch_payload(team_id: int, session_id: str) -> ScannerLlmInputs | None:
    team = Team.objects.get(pk=team_id)
    events_obj = SessionReplayEvents()
    metadata = events_obj.get_metadata(session_id=session_id, team=team)
    if metadata is None:
        raise ApplicationError(f"No replay metadata found for session {session_id}", non_retryable=True)
    duration_seconds = float(metadata["duration"])
    if duration_seconds < MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S:
        raise ApplicationError(
            f"Session {session_id} is only {duration_seconds}s long; min is {MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S}s",
            non_retryable=True,
        )
    # `RecordingMetadata` types this as `int` but it can be missing on sparse fixtures; default to 0.
    active_seconds = metadata.get("active_seconds") or 0
    if active_seconds < MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S:
        raise ApplicationError(
            f"Session {session_id} has only {active_seconds}s of active interaction; min is {MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S}s",
            non_retryable=True,
        )
    if active_seconds > MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S:
        raise ApplicationError(
            f"Session {session_id} has {active_seconds}s of active interaction; max is {MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S}s",
            non_retryable=True,
        )

    columns: list[str] | None = None
    all_rows: list[list[Any]] = []
    events_truncated = False
    for page in range(_MAX_EVENT_PAGES):
        page_columns, page_rows, has_more = events_obj.get_events(
            session_id=session_id,
            team=team,
            metadata=metadata,
            events_to_ignore=_EVENTS_TO_IGNORE,
            extra_fields=_EXTRA_FIELDS,
            limit=_EVENTS_PER_PAGE,
            page=page,
        )
        if page_columns and columns is None:
            columns = list(page_columns)
        if not page_rows:
            break
        all_rows.extend(list(row) for row in page_rows)
        if not has_more:
            break
        if page == _MAX_EVENT_PAGES - 1:
            # We've used every page in our budget and the source still has more.
            events_truncated = True

    if columns is None or not all_rows:
        return None

    processed_columns, processed_rows, url_mapping, window_mapping, event_id_mapping = _process_events(
        columns, all_rows, session_start=metadata["start_time"]
    )
    # Derive from duration; clamp because CH can yield active > duration (tab visibility, clock skew).
    inactive_seconds = max(0.0, duration_seconds - active_seconds)

    return ScannerLlmInputs(
        session_id=session_id,
        team_id=team_id,
        events=EventTable(columns=processed_columns, rows=processed_rows),
        url_mapping=url_mapping,
        window_mapping=window_mapping,
        event_id_mapping=event_id_mapping,
        metadata=SessionMetadata(
            start_time=metadata["start_time"],
            end_time=metadata["end_time"],
            duration_seconds=duration_seconds,
            active_seconds=active_seconds,
            inactive_seconds=inactive_seconds,
            click_count=metadata.get("click_count"),
            keypress_count=metadata.get("keypress_count"),
            mouse_activity_count=metadata.get("mouse_activity_count"),
            start_url=metadata.get("first_url"),
            console_error_count=metadata.get("console_error_count"),
            events_truncated=events_truncated,
        ),
    )


def _process_events(
    raw_columns: list[str], raw_rows: list[list[Any]], *, session_start: dt.datetime
) -> tuple[list[str], list[list[Any]], dict[str, str], dict[str, str], dict[str, EventCitation]]:
    """Dedup, truncate, intern URLs/windows, project uuid into the event_id mapping."""
    uuid_index = raw_columns.index("uuid") if "uuid" in raw_columns else None
    timestamp_index = raw_columns.index("timestamp") if "timestamp" in raw_columns else None
    # All other indexes are over the LLM-visible column set (uuid stripped); compute once.
    visible_columns = [c for i, c in enumerate(raw_columns) if i != uuid_index]
    url_index = visible_columns.index("$current_url") if "$current_url" in visible_columns else None
    window_index = visible_columns.index("$window_id") if "$window_id" in visible_columns else None

    url_tokens: dict[str, str] = {}  # actual -> token; flipped at the end for the prompt
    window_tokens: dict[str, str] = {}
    event_id_mapping: dict[str, EventCitation] = {}
    seen_hashes: set[str] = set()
    processed: list[list[Any]] = []

    for row in raw_rows:
        # Hash the LLM-visible projection (uuid is unique per event and would defeat dedup).
        visible = list(row)
        uuid_value: Any = None
        if uuid_index is not None:
            uuid_value = visible.pop(uuid_index)
        raw_hash = _row_hash(visible)
        if raw_hash in seen_hashes:
            continue
        seen_hashes.add(raw_hash)

        if uuid_value is not None:
            # ClickHouse returns `uuid` as `uuid.UUID`, not str.
            event_id_mapping[raw_hash] = EventCitation(
                uuid=str(uuid_value),
                timestamp_ms=_relative_ms(row[timestamp_index] if timestamp_index is not None else None, session_start),
            )

        # Intern before truncate so the token map keys on the full value, not a clipped prefix.
        if url_index is not None:
            visible[url_index] = _intern(visible[url_index], url_tokens, _URL_PREFIX)
        if window_index is not None:
            visible[window_index] = _intern(visible[window_index], window_tokens, _WINDOW_PREFIX)
        processed.append([raw_hash, *(_truncate(v) for v in visible)])

    output_columns = ["event_id", *visible_columns]
    url_mapping = {token: actual for actual, token in url_tokens.items()}
    window_mapping = {token: actual for actual, token in window_tokens.items()}
    return output_columns, processed, url_mapping, window_mapping, event_id_mapping


def _relative_ms(event_timestamp: Any, session_start: dt.datetime) -> int:
    """Milliseconds since session start; 0 when the timestamp is missing, malformed, earlier than start, or tz-mismatched."""
    if not isinstance(event_timestamp, dt.datetime):
        return 0
    try:
        return max(0, int((event_timestamp - session_start).total_seconds() * 1000))
    except TypeError:
        # Mixed naive/aware datetimes raise here; fall back to 0 like the other defensive branches.
        return 0


def _intern(value: Any, mapping: dict[str, str], prefix: str) -> Any:
    """Replace string `value` with a `<prefix>_N` token, mutating `mapping` (actual -> token); non-strings pass through."""
    if not isinstance(value, str):
        return value
    if value in mapping:
        return mapping[value]
    token = f"{prefix}_{len(mapping) + 1}"
    mapping[value] = token
    return token


def _truncate(value: Any) -> Any:
    """Cap a single field so one oversized value (long stack trace, big elements_chain list) can't blow the prompt."""
    if isinstance(value, str) and len(value) > _MAX_FIELD_LEN:
        return value[:_MAX_FIELD_LEN] + "…[truncated]"
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    return value


def _row_hash(row: list[Any]) -> str:
    """Deterministic 16-char (64-bit) hex of the row contents; identical events collapse to the same id."""
    # `repr` quotes strings and renders `None` as `None`, so a literal "" and a None column don't collide.
    joined = "\0".join(repr(v) for v in row)
    return hashlib.sha256(joined.encode()).hexdigest()[: _EVENT_ID_BYTES * 2]
