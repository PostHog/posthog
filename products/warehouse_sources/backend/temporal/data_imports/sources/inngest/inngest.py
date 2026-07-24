import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.settings import (
    INNGEST_ENDPOINTS,
    InngestEndpointConfig,
)

INNGEST_API_BASE_URL = "https://api.inngest.com"

# Documented max for GET /v1/events (limit is 1-100).
EVENTS_PAGE_SIZE = 100
# First-sync backfill window. Inngest retention is plan-gated (24h free up to 90d enterprise), so
# asking for the longest window just returns whatever history the plan still holds.
DEFAULT_BACKFILL_DAYS = 90
# Emit a fan-out progress log line every N events walked.
FAN_OUT_PROGRESS_LOG_INTERVAL = 1000


class InngestRetryableError(Exception):
    pass


@dataclasses.dataclass
class InngestResumeConfig:
    # Cursor into the /v1/events walk: the internal_id (ULID) of the last event of the last page
    # already yielded downstream.
    cursor: str | None = None
    # The walk's [received_after, received_before] window, pinned at walk start so a resumed
    # attempt continues the exact same window instead of re-deriving it from a moved clock.
    received_after: str | None = None
    received_before: str | None = None


def _get_headers(signing_key: str, environment: str | None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {signing_key}",
        "Accept": "application/json",
    }
    if environment:
        # Signing keys are per environment; the header targets branch/custom environments.
        headers["X-Inngest-Env"] = environment
    return headers


@retry(
    retry=retry_if_exception_type(
        (
            InngestRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
) -> Any:
    response = session.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise InngestRetryableError(f"Inngest API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log only status and URL — never the response body, which can echo arbitrary customer
        # event payloads.
        logger.error(f"Inngest API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(signing_key: str, environment: str | None = None) -> bool:
    """Probe the signing key with the cheapest v1 call (v1 is what the event-driven endpoints
    need, and a signing key that passes v1 also authenticates v2)."""
    try:
        response = make_tracked_session(redact_values=(signing_key,), capture=False).get(
            f"{INNGEST_API_BASE_URL}/v1/events",
            headers=_get_headers(signing_key, environment),
            params={"limit": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def _format_rfc3339(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            return _coerce_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _event_window(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> tuple[str, str]:
    """Compute the [received_after, received_before] RFC3339 window for a /v1/events walk.

    `received_after` defaults to only 1 hour ago server-side, so it is always passed explicitly.
    `received_before` is pinned to "now" so pagination pages over a fixed window while new events
    keep arriving.
    """
    now = datetime.now(UTC)
    after = (
        _coerce_datetime(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )
    if after is None:
        after = now - timedelta(days=DEFAULT_BACKFILL_DAYS)
    # A future-dated watermark (bad ts in source data) would produce an empty inverted window
    # forever; clamp it so the sync self-heals.
    if after > now:
        after = now
    return _format_rfc3339(after), _format_rfc3339(now)


def _normalize_event(item: dict[str, Any]) -> dict[str, Any]:
    # The v1 spec documents `receivedAt` amid otherwise snake_case event fields; accept either
    # spelling (the live casing could not be curl-verified without credentials) and normalize to
    # `received_at` so the incremental/partition column has one stable name.
    camel = item.pop("receivedAt", None)
    snake = item.pop("received_at", None)
    item["received_at"] = camel if camel is not None else snake
    return item


def _normalize_run(run: dict[str, Any], event_received_at: Any) -> dict[str, Any]:
    # `output` is whatever the function handler returned (object, array, scalar, or null);
    # JSON-encode non-string values so the column keeps one stable type across rows.
    output = run.get("output")
    if output is not None and not isinstance(output, str):
        run["output"] = json.dumps(output)
    # The parent event's received time drives the incremental watermark: it tracks exactly how far
    # the events walk has progressed, whereas a run's own timestamps can lag arbitrarily behind
    # (debounced/scheduled runs) and would advance the watermark past unseen events.
    run["event_received_at"] = event_received_at
    return run


def _iter_event_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InngestResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[tuple[list[dict[str, Any]], InngestResumeConfig | None]]:
    """Walk /v1/events over a pinned received-time window, yielding (page rows, resume state).

    The resume state is the checkpoint to persist once the page has been yielded downstream
    (None on the final page). Consumers save it AFTER yielding so a crash re-yields the last
    page rather than skipping it.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.received_after and resume.received_before:
        received_after, received_before = resume.received_after, resume.received_before
        cursor = resume.cursor
        logger.debug(f"Inngest: resuming events walk from cursor={cursor}, window ends {received_before}")
    else:
        received_after, received_before = _event_window(should_use_incremental_field, db_incremental_field_last_value)
        cursor = None

    while True:
        params: dict[str, Any] = {
            "limit": EVENTS_PAGE_SIZE,
            "received_after": received_after,
            "received_before": received_before,
        }
        if cursor:
            params["cursor"] = cursor
        payload = _fetch(session, f"{INNGEST_API_BASE_URL}/v1/events", headers, logger, params=params)
        items = payload.get("data") or []
        # We could not curl-verify whether the cursor is inclusive or exclusive without
        # credentials; drop the cursor event if the API returns it again.
        rows = [_normalize_event(item) for item in items if item.get("internal_id") != cursor]
        if not rows:
            break

        next_cursor = rows[-1].get("internal_id")
        # A full page means there may be more; a same-or-missing cursor would loop forever, so
        # treat it as the end of the walk.
        has_more = len(items) == EVENTS_PAGE_SIZE and bool(next_cursor) and next_cursor != cursor
        next_state = (
            InngestResumeConfig(cursor=next_cursor, received_after=received_after, received_before=received_before)
            if has_more
            else None
        )
        yield rows, next_state

        if not has_more:
            break
        cursor = next_cursor


def _get_event_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InngestResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    for rows, next_state in _iter_event_pages(
        session,
        headers,
        logger,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    ):
        yield rows
        if next_state is not None:
            resumable_source_manager.save_state(next_state)


def _get_function_run_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InngestResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over the events walk, fetching each event's function runs.

    Runs have no list endpoint of their own (v1 and v2 only expose runs per event), so this
    one-request-per-event walk is the only way to enumerate them; after the first sync it is
    bounded by the incremental received-time window. Events with no runs still advance the walk;
    only events with runs contribute rows (and therefore to the watermark, computed from the
    injected `event_received_at`). A per-sync request budget was deliberately NOT added: the
    walk's ordering within the window is unverified, so stopping early could persist a watermark
    past events never walked — silent data loss. Progress is made visible via the periodic log
    below instead.
    """
    # A batch run is returned for every event in its batch, which would duplicate the run_id
    # primary key within one sync. Bounded by the number of runs in the window.
    seen_run_ids: set[str] = set()
    events_walked = 0
    runs_yielded = 0

    for events, next_state in _iter_event_pages(
        session,
        headers,
        logger,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    ):
        rows: list[dict[str, Any]] = []
        for event in events:
            internal_id = event.get("internal_id")
            if not internal_id:
                continue
            payload = _fetch(session, f"{INNGEST_API_BASE_URL}/v1/events/{internal_id}/runs", headers, logger)
            for run in payload.get("data") or []:
                run_id = run.get("run_id")
                if not run_id or run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
                rows.append(_normalize_run(run, event.get("received_at")))
            events_walked += 1
            # Long stretches of run-less events yield no rows, so without this the sync looks
            # stalled while it is really paying one lookup per event.
            if events_walked % FAN_OUT_PROGRESS_LOG_INTERVAL == 0:
                logger.info(
                    f"Inngest: function_runs fan-out progress: events_walked={events_walked}, "
                    f"runs_yielded={runs_yielded + len(rows)}"
                )
        runs_yielded += len(rows)
        if rows:
            yield rows
        if next_state is not None:
            resumable_source_manager.save_state(next_state)


def _drop_redacted_fields(item: dict[str, Any], redacted_fields: tuple[str, ...]) -> dict[str, Any]:
    for field_name in redacted_fields:
        item.pop(field_name, None)
    return item


def _get_v2_list_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: InngestEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Page a v2 list endpoint via its `page.cursor` / `page.hasMore` envelope.

    No `limit` is passed: the documented defaults vary per endpoint and the maxima are
    undocumented, so we accept the server default — these are small inventory lists.
    """
    cursor: str | None = None
    while True:
        params = {"cursor": cursor} if cursor else None
        payload = _fetch(session, f"{INNGEST_API_BASE_URL}{config.path}", headers, logger, params=params)
        items = payload.get("data") or []
        rows = [_drop_redacted_fields(item, config.redacted_fields) for item in items if isinstance(item, dict)]
        if rows:
            yield rows

        page = payload.get("page") or {}
        next_cursor = page.get("cursor")
        if not page.get("hasMore") or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor


def _get_v1_list_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: InngestEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    payload = _fetch(session, f"{INNGEST_API_BASE_URL}{config.path}", headers, logger)
    data = payload.get("data") if isinstance(payload, dict) else payload
    # The v1 spec is ambiguous about whether these small lists come back as an array or a single
    # object; handle both.
    if isinstance(data, dict):
        data = [data]
    rows = [_drop_redacted_fields(item, config.redacted_fields) for item in data or [] if isinstance(item, dict)]
    if rows:
        yield rows


def get_rows(
    signing_key: str,
    environment: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InngestResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INNGEST_ENDPOINTS[endpoint]
    headers = _get_headers(signing_key, environment)
    # One session reused across every page (and every per-event runs request) so urllib3 keeps the
    # connection alive. Register the signing key for value-based redaction and disable sample
    # capture: event payloads and run outputs carry arbitrary customer data the name-based
    # scrubber can't sanitise.
    session = make_tracked_session(redact_values=(signing_key,), capture=False)

    if config.fan_out_runs_per_event:
        yield from _get_function_run_rows(
            session,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.pagination == "events_cursor":
        yield from _get_event_rows(
            session,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.pagination == "v2_cursor":
        yield from _get_v2_list_rows(session, headers, logger, config)
    else:
        yield from _get_v1_list_rows(session, headers, logger, config)


def inngest_source(
    signing_key: str,
    environment: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InngestResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INNGEST_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            signing_key=signing_key,
            environment=environment,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The events walk's ordering within the window is undocumented (and could not be
        # curl-verified without credentials), so declare "desc": the watermark is then persisted
        # only at successful job end from the max value seen, which is correct for any arrival
        # order. Full-refresh endpoints keep the default.
        sort_mode="desc" if config.pagination == "events_cursor" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
