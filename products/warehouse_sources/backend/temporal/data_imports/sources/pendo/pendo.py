import json
import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import (
    DEFAULT_REGION,
    EVENTS_DEFAULT_LOOKBACK_DAYS,
    PENDO_ENDPOINTS,
    PENDO_REGION_BASE_URLS,
)

AGGREGATION_PATH = "/api/v1/aggregation"
# Pendo's aggregation endpoint isn't a bulk export tool (4 GB / 5-minute caps), so we page
# through it in bounded chunks via skip/limit pipeline stages.
AGGREGATION_PAGE_SIZE = 5000
# List endpoints return the whole array in one response; chunk it so we don't hold an
# unbounded list in memory and so resume state can advance per chunk.
LIST_CHUNK_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60
# Pendo itself cuts an aggregation off after 5 minutes, and a busy day of events can take most of that.
EVENTS_REQUEST_TIMEOUT_SECONDS = 300
MAX_RETRIES = 5
# Pendo buckets events by day in the subscription's timezone, which the API does not expose. Noon UTC
# falls in the same local day for every offset from -11h to +14h, so stepping a noon-UTC anchor one
# day at a time requests each local day exactly once.
EVENT_WINDOW_ANCHOR = timedelta(hours=12)
EVENT_ALL_APPS = 'expandAppIds("*")'
# Pendo's daily and weekly reprocessing can add backdated events up to 7 days after the fact, so
# an incremental run re-reads that many days before the watermark's day.
EVENTS_REPROCESSING_OVERLAP_DAYS = 7
# A busy day can hold a very large number of buckets; hand them to the pipeline in bounded batches.
EVENT_BATCH_SIZE = 5000
# Values Pendo aggregates into each event bucket, which change as new events arrive. The remaining
# fields identify the bucket, so they alone form its id and a re-read of a still-open day updates
# the row instead of duplicating it.
EVENT_MEASURE_FIELDS = frozenset(
    {
        "numEvents",
        "numMinutes",
        "rageClickCount",
        "errorClickCount",
        "deadClickCount",
        "uTurnCount",
        "lastTime",
        "lastKeyFrameTimestamp",
    }
)


class PendoRetryableError(Exception):
    pass


@frozen
class PendoResumeConfig:
    # Number of rows already yielded for a list endpoint schema; on resume we skip past them.
    offset: int = 0
    # Sort-field value of the last row yielded for an aggregation endpoint schema. Pendo's
    # aggregation pipeline has no skip/offset stage, so resuming re-filters for values past this.
    last_id: Optional[str] = None
    # ISO date of the next UTC day to request for an event endpoint schema.
    next_day: Optional[str] = None


def get_base_url(region: Optional[str]) -> str:
    return PENDO_REGION_BASE_URLS.get((region or DEFAULT_REGION).lower(), PENDO_REGION_BASE_URLS[DEFAULT_REGION])


def _get_headers(integration_key: str) -> dict[str, str]:
    return {
        "x-pendo-integration-key": integration_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@retry_with_deadline(
    retry=retry_if_exception_type((PendoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> requests.Response:
    response = session.request(method, url, timeout=timeout, **kwargs)

    if response.status_code == 429 or response.status_code >= 500:
        raise PendoRetryableError(f"Pendo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Cap the body so an HTML error page (e.g. a WAF 503) can't blow up the log line.
        logger.error(f"Pendo API error: status={response.status_code}, body={response.text[:500]!r}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(integration_key: str, region: Optional[str]) -> tuple[bool, str | None]:
    # Probe a real list endpoint we also sync: a valid key returns 200 (even with an empty
    # array), a bad/insufficient key returns 401/403.
    url = f"{get_base_url(region)}/api/v1/page"
    try:
        # `redact_values` masks the integration key from logged URLs and captured HTTP samples.
        session = make_tracked_session(redact_values=(integration_key,))
        response = session.get(url, headers=_get_headers(integration_key), timeout=10)
    except (requests.RequestException, OSError):
        return False, "Could not reach Pendo. Check your network connection and the selected region."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Pendo integration key, or the key is missing the required permissions."
    return False, f"Pendo returned an unexpected status code: {response.status_code}"


def _iter_list_endpoint(
    session: requests.Session,
    base_url: str,
    path: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    start_offset: int,
    all_apps: bool,
) -> Iterator[list[dict[str, Any]]]:
    # `expand=*` returns objects across every app in a multi-app subscription rather than
    # just the default app.
    url = f"{base_url}{path}?expand=*" if all_apps else f"{base_url}{path}"
    response = _request(session, "GET", url, logger)
    data = response.json()
    items: list[dict[str, Any]] = data if isinstance(data, list) else data.get("results", [])

    offset = start_offset
    for i in range(offset, len(items), LIST_CHUNK_SIZE):
        chunk = items[i : i + LIST_CHUNK_SIZE]
        yield chunk
        offset += len(chunk)
        resumable_source_manager.save_state(PendoResumeConfig(offset=offset))


def _escape_filter_string(value: str) -> str:
    # Pendo's filter grammar uses JS-style string literals. `last_id` comes from a row's sort
    # field (e.g. visitorId, which a customer's own tracking code can set to an arbitrary
    # string), so escape backslashes and quotes before splicing it into the filter expression.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _iter_aggregation(
    session: requests.Session,
    base_url: str,
    aggregation_source: str,
    sort_field: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    start_after: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}{AGGREGATION_PATH}"
    last_id = start_after

    while True:
        # Sort on a stable id and page via a `>` filter cursor: Pendo's aggregation pipeline
        # has no skip/offset stage (a "skip" step returns a 400 "unknown step type" error).
        pipeline: list[dict[str, Any]] = [
            {"source": {aggregation_source: None}},
            {"sort": [sort_field]},
        ]
        if last_id is not None:
            pipeline.append({"filter": f'{sort_field}>"{_escape_filter_string(last_id)}"'})
        pipeline.append({"limit": AGGREGATION_PAGE_SIZE})

        body = {
            "response": {"mimeType": "application/json"},
            "request": {
                "requestId": f"posthog-{aggregation_source}",
                "pipeline": pipeline,
            },
        }
        response = _request(session, "POST", url, logger, json=body)
        data = response.json()
        rows: list[dict[str, Any]] = data.get("results", []) if isinstance(data, dict) else data

        if not rows:
            break

        yield rows
        last_id = str(rows[-1][sort_field])
        resumable_source_manager.save_state(PendoResumeConfig(last_id=last_id))

        if len(rows) < AGGREGATION_PAGE_SIZE:
            break


def _to_epoch_ms(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _events_start_day(db_incremental_field_last_value: Any, today: date) -> date:
    watermark = _to_epoch_ms(db_incremental_field_last_value)
    if watermark is None:
        return today - timedelta(days=EVENTS_DEFAULT_LOOKBACK_DAYS)
    return datetime.fromtimestamp(watermark / 1000, tz=UTC).date() - timedelta(days=EVENTS_REPROCESSING_OVERLAP_DAYS)


def _with_bucket_id(row: dict[str, Any]) -> dict[str, Any]:
    identity = {key: value for key, value in row.items() if key not in EVENT_MEASURE_FIELDS}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    return {"id": digest, **row}


def _iter_events(
    session: requests.Session,
    base_url: str,
    event_source: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    start_day: date,
    end_day: date,
    all_apps: bool,
    grouped: bool,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}{AGGREGATION_PATH}"
    day = start_day
    source_params = {"appId": EVENT_ALL_APPS} if all_apps else None

    while day <= end_day:
        anchor = datetime.combine(day, time(), tzinfo=UTC) + EVENT_WINDOW_ANCHOR
        body = {
            "response": {"mimeType": "application/json"},
            "request": {
                "requestId": f"posthog-{event_source}",
                "pipeline": [
                    {
                        "source": {
                            event_source: source_params,
                            "timeSeries": {"period": "dayRange", "first": int(anchor.timestamp() * 1000), "count": 1},
                        }
                    }
                ],
            },
        }
        response = _request(session, "POST", url, logger, timeout=EVENTS_REQUEST_TIMEOUT_SECONDS, json=body)
        data = response.json()
        del response
        rows: list[dict[str, Any]] = (data.get("results") or []) if isinstance(data, dict) else data

        day += timedelta(days=1)
        if not rows:
            resumable_source_manager.save_state(PendoResumeConfig(next_day=day.isoformat()))
            resumable_source_manager.safe_point()
            continue

        for start in range(0, len(rows), EVENT_BATCH_SIZE):
            # Only the day's last batch moves the cursor past it, so a resume re-reads a partly written day.
            if start + EVENT_BATCH_SIZE >= len(rows):
                resumable_source_manager.save_state(PendoResumeConfig(next_day=day.isoformat()))
            batch = rows[start : start + EVENT_BATCH_SIZE]
            yield [_with_bucket_id(row) for row in batch] if grouped else batch


def get_rows(
    integration_key: str,
    region: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PENDO_ENDPOINTS[endpoint]
    base_url = get_base_url(region)
    # `redact_values` masks the integration key from logged URLs and captured HTTP samples.
    session = make_tracked_session(headers=_get_headers(integration_key), redact_values=(integration_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.event_source is not None:
        # The last day whose anchor is not in the future.
        end_day = (datetime.now(tz=UTC) - EVENT_WINDOW_ANCHOR).date()
        if resume and resume.next_day:
            start_day = date.fromisoformat(resume.next_day)
            logger.debug(f"Pendo: resuming endpoint={endpoint} from day={start_day}")
        else:
            start_day = _events_start_day(db_incremental_field_last_value, end_day)
        yield from _iter_events(
            session,
            base_url,
            config.event_source,
            logger,
            resumable_source_manager,
            start_day,
            end_day,
            config.all_apps,
            config.grouped_events,
        )
    elif config.is_aggregation:
        if config.aggregation_source is None:
            raise ValueError(f"Endpoint '{endpoint}' is marked as aggregation but has no aggregation_source")
        start_after = resume.last_id if resume else None
        if start_after is not None:
            logger.debug(f"Pendo: resuming endpoint={endpoint} after id={start_after}")
        yield from _iter_aggregation(
            session,
            base_url,
            config.aggregation_source,
            config.primary_keys[0],
            logger,
            resumable_source_manager,
            start_after,
        )
    else:
        if config.path is None:
            raise ValueError(f"Endpoint '{endpoint}' is not an aggregation but has no path")
        start_offset = resume.offset if resume else 0
        if start_offset:
            logger.debug(f"Pendo: resuming endpoint={endpoint} from offset={start_offset}")
        yield from _iter_list_endpoint(
            session,
            base_url,
            config.path,
            logger,
            resumable_source_manager,
            start_offset,
            config.all_apps,
        )


def pendo_source(
    integration_key: str,
    region: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = PENDO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            integration_key=integration_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # No source-level partitioning: Pendo timestamps are epoch-milliseconds, which the
        # datetime partitioner would misread as epoch-seconds, and the aggregation rows carry
        # no stable created_at field. Ship unpartitioned full-refresh tables.
    )
