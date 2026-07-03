import hashlib
import datetime as dt
import itertools
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models import Team
from posthog.models.person.util import get_person_by_distinct_id
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.moments import CoalescedMoment
from products.replay_vision.backend.temporal.constants import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import IneligibleSessionError, IneligibleSessionKind
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import (
    EventTable,
    FetchSessionEventsInputs,
    FetchSessionEventsOutput,
    ResolvedMoment,
    ScannerLlmInputs,
    SessionMetadata,
)

logger = structlog.get_logger(__name__)

# Pagination shape mirrors session_summary's fetcher; without it HogQL applies LimitContext.QUERY's default of 100.
# Events are no longer inlined in the prompt — they're loaded into the table the model queries on demand — so we
# page through the whole session.
_EVENTS_PER_PAGE = 2000

# Noisy SDK-internal events that add no signal for the LLM.
_EVENTS_TO_IGNORE = ["$feature_flag_called"]

# `properties.*` is the HogQL prefix for JSON properties; `uuid` is surfaced to the LLM as the `event_uuid` citation handle.
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
# Fixed-size dedup key — keeps `seen_hashes` bounded on chatty sessions where each row can carry ~KB-sized truncated exception text.
_DEDUP_HASH_BYTES = 8


@activity.defn
@track_activity()
async def fetch_session_events_activity(inputs: FetchSessionEventsInputs) -> FetchSessionEventsOutput:
    """Fetch analytics events for a session and stash in Redis; idempotent — a second call reloads the stored payload."""
    redis_client, redis_key = get_redis_state_client(
        label=StateActivitiesEnum.SESSION_EVENTS,
        state_id=str(inputs.observation_id),
    )
    stored = await get_data_class_from_redis(redis_client, redis_key, ScannerLlmInputs)
    if stored is not None:
        # Re-derive the output from the stored blob so a retried call still hands the workflow the window.
        return FetchSessionEventsOutput(resolved_moment=stored.moment)

    payload = await sync_to_async(_fetch_payload)(inputs.team_id, inputs.session_id, inputs.moment)
    if payload is None:
        raise IneligibleSessionError(
            "No events to analyze",
            kind=IneligibleSessionKind.NO_EVENTS,
        )

    # Persist the session identity so downstream steps read it off the row instead of re-querying ClickHouse.
    await sync_to_async(_persist_session_identity)(inputs.observation_id, payload)

    await store_data_in_redis(redis_client, redis_key, payload.model_dump_json())
    return FetchSessionEventsOutput(resolved_moment=payload.moment)


def _persist_session_identity(observation_id: Any, payload: ScannerLlmInputs) -> None:
    email: str | None = None
    if payload.distinct_id:
        try:
            person = get_person_by_distinct_id(payload.team_id, payload.distinct_id)
            email = person.properties.get("email") if person is not None else None
        except Exception:
            logger.warning(
                "replay_vision.fetch.subject_email_lookup_failed", observation_id=str(observation_id), exc_info=True
            )
    ReplayObservation.objects.filter(pk=observation_id).update(
        distinct_id=payload.distinct_id,
        recording_subject_email=email,
        session_started_at=payload.metadata.start_time,
        window_start_offset_s=payload.moment.window_start_s if payload.moment else None,
        window_end_offset_s=payload.moment.window_end_s if payload.moment else None,
    )


def _resolve_moment(moment: CoalescedMoment, *, start_time: dt.datetime, duration_seconds: float) -> ResolvedMoment:
    """Place the moment's absolute window onto the recording timeline, clamped to the recording bounds.

    Uses the same event-timestamp − recording-start arithmetic as `_relative_ms`, so the clip and the
    events tool agree on where events sit; the before/after margins absorb residual clock skew.
    """
    window_start_s = (moment.window_start - start_time).total_seconds()
    window_end_s = (moment.window_end - start_time).total_seconds()
    clamped_start = max(0.0, window_start_s)
    clamped_end = min(duration_seconds, window_end_s)
    if clamped_end <= clamped_start:
        raise IneligibleSessionError(
            f"Moment around {moment.anchor_event} falls outside the recording "
            f"({round(window_start_s, 1)}s..{round(window_end_s, 1)}s of a {round(duration_seconds, 1)}s recording)",
            kind=IneligibleSessionKind.MOMENT_OUTSIDE_RECORDING,
        )
    return ResolvedMoment(
        window_start_s=clamped_start,
        window_end_s=clamped_end,
        anchor_event=moment.anchor_event,
        anchor_offset_s=min(duration_seconds, max(0.0, (moment.anchor_timestamp - start_time).total_seconds())),
        occurrence_count=moment.occurrence_count,
    )


def _fetch_payload(team_id: int, session_id: str, moment: CoalescedMoment | None = None) -> ScannerLlmInputs | None:
    team = Team.objects.get(pk=team_id)
    events_obj = SessionReplayEvents()
    metadata = events_obj.get_metadata(session_id=session_id, team=team)
    if metadata is None:
        raise IneligibleSessionError(
            "No replay metadata found",
            kind=IneligibleSessionKind.NO_RECORDING,
        )
    duration_seconds = float(metadata["duration"])
    if duration_seconds < MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S:
        raise IneligibleSessionError(
            f"Only {round(duration_seconds, 1)}s long; min is {MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S}s",
            kind=IneligibleSessionKind.TOO_SHORT,
        )
    # `RecordingMetadata` types this as `int` but it can be missing on sparse fixtures; default to 0.
    active_seconds = metadata.get("active_seconds") or 0
    if active_seconds < MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S:
        raise IneligibleSessionError(
            f"Only {round(active_seconds, 1)}s of active interaction; min is {MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S}s",
            kind=IneligibleSessionKind.TOO_INACTIVE,
        )
    # Moments render a bounded clip, so the whole-recording length cap doesn't apply.
    if moment is None and active_seconds > MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S:
        raise IneligibleSessionError(
            f"{round(active_seconds, 1)}s of active interaction; max is {MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S}s",
            kind=IneligibleSessionKind.TOO_LONG,
        )
    resolved_moment = (
        _resolve_moment(moment, start_time=metadata["start_time"], duration_seconds=duration_seconds)
        if moment is not None
        else None
    )

    columns: list[str] | None = None
    all_rows: list[list[Any]] = []
    for page in itertools.count():
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

    if columns is None or not all_rows:
        return None

    processed_columns, processed_rows, url_mapping, window_mapping, event_timestamps = _process_events(
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
        event_timestamps=event_timestamps,
        distinct_id=metadata.get("distinct_id"),
        moment=resolved_moment,
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
        ),
    )


def _process_events(
    raw_columns: list[str], raw_rows: list[list[Any]], *, session_start: dt.datetime
) -> tuple[list[str], list[list[Any]], dict[str, str], dict[str, str], dict[str, int]]:
    """Dedup, truncate, intern URLs/windows, surface uuid as `event_uuid` for the LLM, and build the uuid → relative-ms lookup."""
    uuid_index = raw_columns.index("uuid") if "uuid" in raw_columns else None
    timestamp_index = raw_columns.index("timestamp") if "timestamp" in raw_columns else None
    # All other indexes are over the LLM-visible column set (uuid stripped); compute once.
    visible_columns = [c for i, c in enumerate(raw_columns) if i != uuid_index]
    url_index = visible_columns.index("$current_url") if "$current_url" in visible_columns else None
    window_index = visible_columns.index("$window_id") if "$window_id" in visible_columns else None

    url_tokens: dict[str, str] = {}  # actual -> token; flipped at the end for the prompt
    window_tokens: dict[str, str] = {}
    event_timestamps: dict[str, int] = {}
    seen_hashes: set[str] = set()
    processed: list[list[Any]] = []

    for row in raw_rows:
        visible = list(row)
        uuid_value: Any = None
        if uuid_index is not None:
            uuid_value = visible.pop(uuid_index)
        dedup_key = _row_hash(visible)
        if dedup_key in seen_hashes:
            continue
        seen_hashes.add(dedup_key)

        uuid_str = str(uuid_value) if uuid_value is not None else ""
        if uuid_str:
            event_timestamps[uuid_str] = _relative_ms(
                row[timestamp_index] if timestamp_index is not None else None, session_start
            )

        # Intern before truncate so the token map keys on the full value, not a clipped prefix.
        if url_index is not None:
            visible[url_index] = _intern(visible[url_index], url_tokens, _URL_PREFIX)
        if window_index is not None:
            visible[window_index] = _intern(visible[window_index], window_tokens, _WINDOW_PREFIX)
        processed.append([uuid_str, *(_truncate(v) for v in visible)])

    output_columns = ["event_uuid", *visible_columns]
    url_mapping = {token: actual for actual, token in url_tokens.items()}
    window_mapping = {token: actual for actual, token in window_tokens.items()}
    return output_columns, processed, url_mapping, window_mapping, event_timestamps


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
    """Fixed-size in-process dedup key; bounds `seen_hashes` memory on chatty sessions where each visible row can be KBs."""
    # `repr` keeps `None` distinct from the literal `"None"` string.
    joined = "\0".join(repr(v) for v in row)
    return hashlib.sha256(joined.encode()).hexdigest()[: _DEDUP_HASH_BYTES * 2]
