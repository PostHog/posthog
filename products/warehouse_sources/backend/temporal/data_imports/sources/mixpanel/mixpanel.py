import time
import random
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import orjson
import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.settings import (
    DEFAULT_EXPORT_LOOKBACK_DAYS,
    MIXPANEL_ENDPOINTS,
    REGION_HOSTS,
)

# Rows buffered before yielding a batch. The pipeline batches again downstream, but
# yielding in chunks keeps memory bounded while streaming the JSONL export.
CHUNK_SIZE = 5000
ENGAGE_PAGE_SIZE = 1000
REQUEST_TIMEOUT = 120

# Let tenacity be the only retry layer. The default tracked-session retry only retries
# GET/HEAD/OPTIONS at the urllib3 level, which would give the GET endpoints a much larger
# (and uneven) effective retry budget than the POST ones.
NO_URLLIB_RETRY = Retry(total=0)

# Upper bound on how long we'll honor a server-provided `Retry-After`. Mixpanel can hand
# back a cool-down longer than our default backoff; we wait for it, but cap it so a large
# (or hostile) value can't pin a worker thread for an unbounded stretch.
MAX_RETRY_AFTER_SECONDS = 120


class MixpanelRetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        # Seconds the server asked us to wait before retrying (from the `Retry-After`
        # header), or None when the response didn't provide one.
        self.retry_after = retry_after


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a `Retry-After` header into seconds-from-now.

    The header is either delta-seconds (`"30"`) or an HTTP-date. Returns None for a
    missing, malformed, or already-elapsed value so the caller falls back to its default
    backoff."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    try:
        retry_dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_dt.tzinfo is None:
        retry_dt = retry_dt.replace(tzinfo=UTC)
    delta = (retry_dt - datetime.now(UTC)).total_seconds()
    return delta if delta > 0 else None


# Backoff used when the server gives us no `Retry-After` to honor.
_EXPONENTIAL_JITTER = wait_exponential_jitter(initial=2, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    """Prefer the server's `Retry-After` cool-down on a 429/5xx; otherwise back off
    exponentially with jitter. Retrying before the server's stated window just earns
    another 429 and wastes the (small) retry budget."""
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None else None
    if isinstance(exc, MixpanelRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _EXPONENTIAL_JITTER(retry_state)


@dataclasses.dataclass
class MixpanelResumeConfig:
    # Raw export resumes at the day window we have not yet completed.
    from_date: Optional[str] = None
    # Engage resumes at a session id + page from the previous query.
    session_id: Optional[str] = None
    page: Optional[int] = None


def _hosts(region: str) -> tuple[str, str]:
    return REGION_HOSTS.get(region, REGION_HOSTS["us"])


def _query_base(region: str) -> str:
    return _hosts(region)[0]


def _export_base(region: str) -> str:
    return _hosts(region)[1]


def _flatten_event(event: dict[str, Any]) -> dict[str, Any]:
    """Lift the `properties` sub-object of a raw export event to the top level.

    The export API returns `{"event": "...", "properties": {"time": ..., "distinct_id":
    ..., "$insert_id": ..., ...}}`. Flattening keeps `time` / `distinct_id` / `$insert_id`
    addressable as columns (and as primary/partition keys)."""
    row: dict[str, Any] = {"event": event.get("event")}
    properties = event.get("properties")
    if isinstance(properties, dict):
        row.update(properties)
    return row


def _flatten_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Lift the `$properties` sub-object of an Engage profile to the top level."""
    row: dict[str, Any] = {"$distinct_id": profile.get("$distinct_id")}
    properties = profile.get("$properties")
    if isinstance(properties, dict):
        row.update(properties)
    return row


def _to_date(value: Any) -> Optional[date]:
    """Coerce a stored incremental cursor (epoch seconds, datetime, or ISO string) to a date."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).date()
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def validate_credentials(
    region: str,
    username: str,
    secret: str,
    project_id: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Cheap probe to confirm the service account works.

    Mixpanel returns 401 for a bad credential and 403 when the credential is valid but
    lacks access to the requested resource. At source-create (`schema_name is None`) we
    accept 403 — users may only have granted scope for the endpoints they want — and only
    treat 401 as a hard failure."""
    url = f"{_query_base(region)}/api/query/cohorts/list"
    try:
        response = make_tracked_session(retry=NO_URLLIB_RETRY).post(
            url,
            params={"project_id": project_id},
            auth=(username, secret),
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except Exception:
        return False, "Could not reach Mixpanel. Check the region and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Mixpanel rejected the service account credentials. Check the username, secret, and project ID."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "The service account does not have access to this resource in the selected project."

    return False, f"Mixpanel returned an unexpected status ({response.status_code}) while validating credentials."


def _check_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> requests.Response:
    """Classify a Mixpanel response: 429/5xx are retryable, other 4xx are terminal."""
    if response.status_code == 429 or response.status_code >= 500:
        headers = getattr(response, "headers", None) or {}
        retry_after = _parse_retry_after(headers.get("Retry-After"))
        raise MixpanelRetryableError(
            f"Mixpanel API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    if not response.ok:
        logger.error(f"Mixpanel API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response


@retry(
    retry=retry_if_exception_type((MixpanelRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=_retry_wait,
    reraise=True,
)
def _request(
    method: str,
    url: str,
    *,
    username: str,
    secret: str,
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
    stream: bool = False,
) -> requests.Response:
    response = make_tracked_session(retry=NO_URLLIB_RETRY).request(
        method,
        url,
        params=params,
        auth=(username, secret),
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
        stream=stream,
    )
    return _check_response(response, url, logger)


# The export body is read lazily while iterating `iter_lines`, i.e. outside `_request`'s
# retry. A connection dropped mid-day surfaces there (`requests` wraps the underlying
# `IncompleteRead` as `ChunkedEncodingError`), so it must be retried separately or a single
# truncated download fails the whole sync.
STREAM_MAX_ATTEMPTS = 5
_STREAM_RETRYABLE_ERRORS = (
    requests.exceptions.ChunkedEncodingError,
    requests.ConnectionError,
    requests.ReadTimeout,
)


def _stream_export_day(
    url: str,
    *,
    username: str,
    secret: str,
    project_id: str,
    from_date: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Stream one UTC day of the raw export as `CHUNK_SIZE` batches.

    On a transient mid-stream drop the whole day is re-fetched from the start; already-yielded
    rows are re-emitted, but merge dedupes them on `$insert_id` (the same property the day-level
    resume relies on)."""
    params = {"from_date": from_date, "to_date": from_date, "project_id": project_id}
    for attempt in range(1, STREAM_MAX_ATTEMPTS + 1):
        try:
            with _request(
                "GET", url, username=username, secret=secret, logger=logger, params=params, stream=True
            ) as response:
                batch: list[dict[str, Any]] = []
                for line in response.iter_lines():
                    if not line:
                        continue
                    batch.append(_flatten_event(orjson.loads(line)))
                    if len(batch) >= CHUNK_SIZE:
                        yield batch
                        batch = []
                if batch:
                    yield batch
            return
        except _STREAM_RETRYABLE_ERRORS as e:
            if attempt == STREAM_MAX_ATTEMPTS:
                logger.warning(
                    f"Mixpanel export: stream for {from_date} dropped ({type(e).__name__}); "
                    f"giving up after {STREAM_MAX_ATTEMPTS} attempts"
                )
                raise
            backoff = min(60.0, 2.0 * 2 ** (attempt - 1)) + random.uniform(0, 1)
            logger.warning(
                f"Mixpanel export: stream for {from_date} dropped ({type(e).__name__}); "
                f"re-fetching day (attempt {attempt}/{STREAM_MAX_ATTEMPTS})"
            )
            time.sleep(backoff)


def _iter_export(
    region: str,
    username: str,
    secret: str,
    project_id: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[MixpanelResumeConfig],
    start_date: date,
    end_date: date,
) -> Iterator[list[dict[str, Any]]]:
    """Stream the raw event export one UTC day at a time.

    The export API has no offset/cursor pagination, so day windows are both our
    incremental granularity and our resume granularity. We save state pointing at the
    *next* day only after a day's batches have been yielded, so a crash re-fetches the
    in-flight day (merge dedupes on `$insert_id`)."""
    url = f"{_export_base(region)}/api/2.0/export"

    resume = manager.load_state() if manager.can_resume() else None
    resumed_from = _to_date(resume.from_date) if resume and resume.from_date else None
    current = resumed_from or start_date
    if resumed_from:
        logger.debug(f"Mixpanel export: resuming from {resumed_from.isoformat()}")

    while current <= end_date:
        yield from _stream_export_day(
            url,
            username=username,
            secret=secret,
            project_id=project_id,
            from_date=current.isoformat(),
            logger=logger,
        )

        # Day complete: advance the resume cursor so a restart skips finished days.
        next_day = current + timedelta(days=1)
        manager.save_state(MixpanelResumeConfig(from_date=next_day.isoformat()))
        current = next_day


def _iter_engage(
    region: str,
    username: str,
    secret: str,
    project_id: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[MixpanelResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Page through user profiles using the Engage API's session-based pagination."""
    url = f"{_query_base(region)}/api/query/engage"

    resume = manager.load_state() if manager.can_resume() else None
    page = resume.page if resume and resume.page is not None else 0
    session_id = resume.session_id if resume else None
    if resume and resume.page is not None:
        logger.debug(f"Mixpanel engage: resuming from page {page}")

    while True:
        params: dict[str, Any] = {"project_id": project_id, "page": page}
        if session_id:
            params["session_id"] = session_id

        response = _request("POST", url, username=username, secret=secret, logger=logger, params=params)
        data = response.json()

        results = data.get("results", [])
        if not results:
            break

        session_id = data.get("session_id", session_id)
        page_size = data.get("page_size", ENGAGE_PAGE_SIZE)

        yield [_flatten_profile(profile) for profile in results]

        page += 1
        manager.save_state(MixpanelResumeConfig(session_id=session_id, page=page))

        if len(results) < page_size:
            break


def _fetch_cohorts(
    region: str, username: str, secret: str, project_id: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    url = f"{_query_base(region)}/api/query/cohorts/list"
    response = _request("POST", url, username=username, secret=secret, logger=logger, params={"project_id": project_id})
    data = response.json()
    # The cohorts endpoint returns a bare list; tolerate a `results` wrapper defensively.
    rows = data if isinstance(data, list) else data.get("results", [])
    if rows:
        yield rows


def _fetch_annotations(
    region: str, username: str, secret: str, project_id: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    url = f"{_query_base(region)}/api/app/projects/{project_id}/annotations"
    response = _request("GET", url, username=username, secret=secret, logger=logger)
    data = response.json()
    rows = data if isinstance(data, list) else data.get("results", [])
    if rows:
        yield rows


def get_rows(
    region: str,
    username: str,
    secret: str,
    project_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[MixpanelResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint == "export":
        last_value_date = _to_date(db_incremental_field_last_value) if should_use_incremental_field else None
        end_date = datetime.now(UTC).date()
        start_date = last_value_date or (end_date - timedelta(days=DEFAULT_EXPORT_LOOKBACK_DAYS))
        # A future cursor (clock skew or bad event data) would make start_date > end_date and the
        # day loop a no-op, silently skipping the sync. Clamp to today so we still sync the latest day.
        if start_date > end_date:
            logger.warning(
                f"Mixpanel export: incremental cursor {start_date.isoformat()} is in the future; syncing today"
            )
            start_date = end_date
        yield from _iter_export(
            region, username, secret, project_id, logger, manager, start_date=start_date, end_date=end_date
        )
    elif endpoint == "engage":
        yield from _iter_engage(region, username, secret, project_id, logger, manager)
    elif endpoint == "cohorts":
        yield from _fetch_cohorts(region, username, secret, project_id, logger)
    elif endpoint == "annotations":
        yield from _fetch_annotations(region, username, secret, project_id, logger)
    else:
        raise ValueError(f"Unknown Mixpanel endpoint: {endpoint}")


def mixpanel_source(
    region: str,
    username: str,
    secret: str,
    project_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[MixpanelResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = MIXPANEL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            username=username,
            secret=secret,
            project_id=project_id,
            endpoint=endpoint,
            logger=logger,
            manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format=endpoint_config.partition_format if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )
