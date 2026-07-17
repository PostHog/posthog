import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.settings import METAPLANE_ENDPOINTS

# "dev" is part of the vendor's production domain, not a sandbox.
METAPLANE_BASE_URL = "https://dev.api.metaplane.dev/v1"

# The evaluation-history endpoint caps pages at 500 records.
EVALUATION_PAGE_LIMIT = 500
REQUEST_TIMEOUT_SECONDS = 60


class MetaplaneRetryableError(Exception):
    pass


@dataclasses.dataclass
class MetaplaneResumeConfig:
    # Bookmark into the monitor fan-out of the `monitor_evaluations` endpoint. A stable
    # monitor-ID bookmark (not a positional index) so monitors added/removed between a crash
    # and the retry can't resume us into the wrong monitor. None for the other endpoints,
    # which complete in a handful of requests and just restart on retry.
    monitor_id: str | None = None
    # `createdAt` of the last evaluation fetched for that monitor — the next page starts here.
    cursor: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    # Metaplane expects the raw API key in the Authorization header (no Bearer prefix).
    return {
        "Authorization": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental value as the ISO 8601 / RFC 3339 timestamp Metaplane returns."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def validate_credentials(api_key: str) -> bool:
    """Probe the connection list to confirm the API key is genuine.

    Metaplane API keys are account-wide (no per-endpoint scopes), so one cheap probe
    covers every endpoint.
    """
    try:
        response = make_tracked_session().get(
            f"{METAPLANE_BASE_URL}/connections",
            headers=_get_headers(api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((MetaplaneRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> Any:
    response = session.request(method, url, headers=headers, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise MetaplaneRetryableError(f"Metaplane API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during fan-out (a monitor/connection deleted mid-sync) and handled
        # by callers; anything else is a hard failure.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Metaplane API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _get_connections(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    data = _request(session, "GET", f"{METAPLANE_BASE_URL}/connections", headers, logger)
    return data if isinstance(data, list) else []


def _get_monitors_for_connection(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger, connection_id: str
) -> list[dict[str, Any]]:
    try:
        data = _request(
            session,
            "GET",
            f"{METAPLANE_BASE_URL}/monitors/connection/{connection_id}?includeDisabled=true",
            headers,
            logger,
        )
    except requests.HTTPError as exc:
        # A connection deleted between enumeration and this fetch 404s — skip it rather than
        # failing the sync; its monitors are genuinely gone.
        if exc.response is not None and exc.response.status_code == 404:
            logger.warning(f"Metaplane: connection {connection_id} not found while listing monitors, skipping")
            return []
        raise
    return data.get("data", []) if isinstance(data, dict) else []


def _get_monitor_rows(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for connection in _get_connections(session, headers, logger):
        monitors = _get_monitors_for_connection(session, headers, logger, connection["id"])
        if monitors:
            yield monitors


def _get_connection_sync_status_rows(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for connection in _get_connections(session, headers, logger):
        try:
            status = _request(
                session,
                "GET",
                f"{METAPLANE_BASE_URL}/connections/{connection['id']}/sync/status",
                headers,
                logger,
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Metaplane: no sync status for connection {connection['id']}, skipping")
                continue
            raise
        if isinstance(status, dict):
            # Some connection types never sync; make sure the row still keys on the connection.
            status.setdefault("connectionId", connection["id"])
            rows.append(status)
    if rows:
        yield rows


def _get_evaluation_page(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    monitor_id: str,
    cursor: str | None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"sortOrder": "ASC", "limit": EVALUATION_PAGE_LIMIT}
    if cursor:
        body["createdAt"] = cursor
    try:
        data = _request(
            session,
            "POST",
            f"{METAPLANE_BASE_URL}/monitors/evaluation-history/{monitor_id}",
            headers,
            logger,
            json_body=body,
        )
    except requests.HTTPError as exc:
        # A monitor deleted (or never run/modeled) 404s — treat as an empty history.
        if exc.response is not None and exc.response.status_code == 404:
            logger.warning(f"Metaplane: no evaluation history for monitor {monitor_id}, skipping")
            return []
        raise
    return data if isinstance(data, list) else []


def _get_evaluation_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetaplaneResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every monitor, paging each monitor's evaluation history ascending.

    Incremental runs start each monitor's history from the table-wide `createdAt` watermark.
    This runs report sort_mode="desc" (see metaplane_source) so the watermark persists only
    at successful job end — mid-run, monitor B's old evaluations arrive after monitor A's new
    ones, so per-batch ascending checkpoints would corrupt the watermark. One consequence:
    monitors created after the initial sync only backfill evaluations from the current
    watermark forward; a full refresh re-pulls complete history.
    """
    monitor_ids: list[str] = []
    for connection in _get_connections(session, headers, logger):
        monitor_ids.extend(
            monitor["id"] for monitor in _get_monitors_for_connection(session, headers, logger, connection["id"])
        )

    initial_cursor = (
        _format_datetime(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else None
    )

    # Resolve the saved monitor-ID bookmark to the slice of monitors still to process. If the
    # bookmarked monitor no longer exists, start over — merge dedupes re-pulled rows on the
    # primary key. `resume_cursor` is consumed by the first monitor only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = monitor_ids
    resume_cursor: str | None = None
    if resume is not None and resume.monitor_id is not None and resume.monitor_id in monitor_ids:
        remaining = monitor_ids[monitor_ids.index(resume.monitor_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Metaplane: resuming monitor_evaluations from monitor_id={resume.monitor_id}")

    for index, monitor_id in enumerate(remaining):
        cursor = resume_cursor or initial_cursor
        resume_cursor = None  # only the resumed-into monitor uses the saved cursor

        while True:
            rows = _get_evaluation_page(session, headers, logger, monitor_id, cursor)
            if not rows:
                break

            for row in rows:
                row["monitorId"] = monitor_id
            yield rows

            # A page shorter than the limit is the last one.
            if len(rows) < EVALUATION_PAGE_LIMIT:
                break

            next_cursor = rows[-1].get("createdAt")
            if not next_cursor or next_cursor == cursor:
                # The cursor didn't advance — a full page of identical timestamps would
                # otherwise loop forever (the API docs don't state cursor inclusivity).
                logger.warning(
                    f"Metaplane: evaluation cursor did not advance for monitor {monitor_id}, stopping pagination"
                )
                break

            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            resumable_source_manager.save_state(MetaplaneResumeConfig(monitor_id=monitor_id, cursor=next_cursor))
            cursor = next_cursor

        # Advance the bookmark to the next monitor so a crash between monitors resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(MetaplaneResumeConfig(monitor_id=remaining[index + 1], cursor=None))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetaplaneResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    headers = _get_headers(api_key)
    # One session reused across every request so urllib3 keeps the connection alive
    # instead of re-handshaking per request.
    session = make_tracked_session()

    if endpoint == "connections":
        connections = _get_connections(session, headers, logger)
        if connections:
            yield connections
    elif endpoint == "monitors":
        yield from _get_monitor_rows(session, headers, logger)
    elif endpoint == "connection_sync_statuses":
        yield from _get_connection_sync_status_rows(session, headers, logger)
    elif endpoint == "monitor_evaluations":
        yield from _get_evaluation_rows(
            session,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        raise ValueError(f"Unknown Metaplane endpoint: {endpoint}")


def metaplane_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetaplaneResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = METAPLANE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The evaluation fan-out persists the incremental watermark only at successful job end
        # (desc mode): a partial run's max says nothing about monitors it never reached, so
        # per-batch persistence could advance the watermark past rows a crashed run still owes.
        sort_mode="desc" if endpoint == "monitor_evaluations" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
