import time
import datetime as dt
import dataclasses
import collections.abc
from typing import Any

from django.conf import settings
from django.db import OperationalError, close_old_connections

import requests
import structlog
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.settings import (
    GOOGLE_ANALYTICS_REPORT_SCHEMAS,
)

logger = structlog.get_logger(__name__)

GA4_API_BASE = "https://analyticsdata.googleapis.com/v1beta"

# GA4 standard properties retain aggregate report data well beyond event-level
# retention, so a 2-year initial backfill is safe and matches what other GA4
# connectors default to.
HISTORY_DAYS = 730

# GA4 can re-state a day's aggregates for up to ~48h after the day ends
# (processing latency), so incremental syncs re-fetch a small window before the
# last synced date and merge-mode dedupe replaces the stale rows.
LOOKBACK_DAYS = 2

# Each runReport call covers one date-range chunk; offset pagination walks rows
# within the chunk. Chunking bounds response payloads and gives resume points,
# while staying far cheaper on Data API quota tokens than day-by-day requests.
CHUNK_DAYS = 30
PAGE_LIMIT = 50000  # runReport allows up to 250k rows/request; keep payloads modest

# Shared runReport retry policy for transient failures: 429 RESOURCE_EXHAUSTED
# quota exhaustion (property tokens, concurrent requests) and 5xx server errors.
# Both are transient — back off and retry inline, then fall back to a Temporal
# activity retry via the resumable state.
RUNREPORT_MAX_RETRIES = 5
RUNREPORT_BACKOFF_BASE_SECONDS = 5.0

_INTEGER_METRIC_TYPES = frozenset({"TYPE_INTEGER"})


class GoogleAnalyticsQuotaExceededError(Exception):
    """Raised when Data API quota stays exhausted after in-line retries.

    Deliberately NOT matched by `get_non_retryable_errors` so Temporal retries
    the activity later (the resumable source picks up from the last saved
    chunk), which is the right recovery for hourly/daily property token quotas.
    """


@dataclasses.dataclass
class GoogleAnalyticsResumeConfig:
    chunk_start: str  # ISO date of the chunk currently being fetched
    offset: int  # next row offset within that chunk


def _backoff_sleep(attempt: int) -> None:
    """Sleep before the next retry: linear growth capped at 30s (2s, 4s, 6s, ...)."""
    time.sleep(min(2 * attempt, 30))


_MAX_INTEGRATION_FETCH_ATTEMPTS = 4


def _get_integration(integration_id: int, team_id: int) -> Integration:
    """Fetch the OAuth ``Integration`` row, retrying a transient DB failure with backoff.

    Temporal activities run in a long-lived worker that never goes through Django's request
    cycle, so a pooled Postgres connection can be closed server-side while it sits idle, or the
    connection pooler can reject the query with a wait timeout when the pool is saturated. Both
    surface as a transient ``OperationalError`` and both clear once a healthy connection is used.
    ``close_old_connections()`` evicts connections already known to be stale (and, after a failed
    query marks one unusable, drops it), so each attempt runs on a fresh connection; the short
    backoff also gives a saturated pool time to drain rather than retrying straight back into the
    same wait timeout. This read is idempotent, so it is safe to repeat. ``Integration.DoesNotExist``
    is left to propagate.
    """
    attempt = 0
    while True:
        close_old_connections()
        try:
            return Integration.objects.get(id=integration_id, team_id=team_id)
        except OperationalError:
            attempt += 1
            if attempt >= _MAX_INTEGRATION_FETCH_ATTEMPTS:
                raise
            _backoff_sleep(attempt)


def _credentials(integration_id: int, team_id: int) -> OAuthCredentials:
    integration = _get_integration(integration_id, team_id)
    return OAuthCredentials(
        token=None,
        refresh_token=integration.refresh_token,
        client_id=settings.GOOGLE_ANALYTICS_APP_CLIENT_ID,
        client_secret=settings.GOOGLE_ANALYTICS_APP_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )


def google_analytics_session(integration_id: int, team_id: int) -> AuthorizedSession:
    creds = _credentials(integration_id, team_id)
    session = AuthorizedSession(creds)
    adapter = make_tracked_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def normalize_property_id(property_id: str) -> str:
    """Accept both a bare numeric ID and the `properties/123` resource name users may paste."""
    cleaned = property_id.strip()
    if cleaned.startswith("properties/"):
        cleaned = cleaned[len("properties/") :]
    return cleaned


def get_property_metadata(session: AuthorizedSession, property_id: str) -> dict[str, Any]:
    """Fetch the property's dimension/metric metadata — the cheapest call that proves read access."""
    pid = normalize_property_id(property_id)
    response = session.get(f"{GA4_API_BASE}/properties/{pid}/metadata")
    response.raise_for_status()
    return response.json()


def _is_quota_error(response: requests.Response) -> bool:
    """The Data API reports quota exhaustion as 429 RESOURCE_EXHAUSTED — unlike
    older Google APIs it does not overload 403 for rate limits."""
    return response.status_code == 429


def _is_retryable_server_error(response: requests.Response) -> bool:
    """5xx responses (e.g. 503 Service Unavailable) are transient backend errors —
    back off and retry inline rather than failing the chunk."""
    return 500 <= response.status_code < 600


def _runreport_backoff_seconds(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before retrying a transient error: honor `Retry-After`, else exponential."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return RUNREPORT_BACKOFF_BASE_SECONDS * (2**attempt)


def _run_report(
    session: AuthorizedSession,
    property_id: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    metrics: list[str],
    offset: int,
    limit: int = PAGE_LIMIT,
) -> dict[str, Any]:
    pid = normalize_property_id(property_id)
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": dim} for dim in dimensions],
        "metrics": [{"name": metric} for metric in metrics],
        # Ascending date order keeps the pipeline's incremental watermark moving forward.
        "orderBys": [{"dimension": {"dimensionName": "date"}}],
        "limit": limit,
        "offset": offset,
    }
    url = f"{GA4_API_BASE}/properties/{pid}:runReport"

    for attempt in range(RUNREPORT_MAX_RETRIES + 1):
        response = session.post(url, json=body)
        if response.ok:
            return response.json()

        # Surface Google's real reason — raise_for_status() discards the body where it lives.
        logger.warning(
            "GA4 runReport failed",
            property_id=pid,
            status_code=response.status_code,
            body=response.text,
        )

        is_quota = _is_quota_error(response)
        if not is_quota and not _is_retryable_server_error(response):
            # Permission / bad-request errors are fatal — let the HTTPError bubble up so
            # `get_non_retryable_errors` can match "403 Client Error" / "401 Client Error".
            response.raise_for_status()

        if attempt == RUNREPORT_MAX_RETRIES:
            if is_quota:
                raise GoogleAnalyticsQuotaExceededError(
                    f"Data API quota for property '{pid}' still exhausted after {RUNREPORT_MAX_RETRIES} retries"
                )
            # A transient 5xx that never cleared — surface the HTTPError so Temporal retries the activity.
            response.raise_for_status()

        wait = _runreport_backoff_seconds(response, attempt)
        logger.warning("GA4 runReport failed, backing off", property_id=pid, attempt=attempt, wait_seconds=wait)
        time.sleep(wait)

    # Unreachable: the loop either returns, raises for status, or raises the quota error.
    raise AssertionError("unreachable")


def _parse_ga4_date(value: str) -> dt.date | str:
    """GA4 returns the `date` dimension as YYYYMMDD."""
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return value


def _convert_metric_value(value: str, metric_type: str) -> Any:
    try:
        if metric_type in _INTEGER_METRIC_TYPES:
            return int(value)
        return float(value)
    except (TypeError, ValueError):
        return value


def _rows_to_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten runReport's header/value arrays into per-row dicts with typed values."""
    dimension_names = [header["name"] for header in payload.get("dimensionHeaders", [])]
    metric_headers = payload.get("metricHeaders", [])

    out: list[dict[str, Any]] = []
    for row in payload.get("rows", []):
        record: dict[str, Any] = {}
        for name, dim_value in zip(dimension_names, row.get("dimensionValues", [])):
            value = dim_value["value"]
            record[name] = _parse_ga4_date(value) if name == "date" else value
        for header, metric_value in zip(metric_headers, row.get("metricValues", [])):
            record[header["name"]] = _convert_metric_value(metric_value["value"], header.get("type", ""))
        out.append(record)
    return out


def _today() -> dt.date:
    return dt.date.today()


def _initial_start_date(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=HISTORY_DAYS)


def _resolve_window(today: dt.date, db_incremental_field_last_value: Any) -> tuple[dt.date, dt.date]:
    # End at yesterday: today's aggregates are still accruing and would land as
    # permanently stale rows for schemas whose primary key is just `date`.
    end_date = today - dt.timedelta(days=1)
    if db_incremental_field_last_value is None:
        return _initial_start_date(today), end_date

    if isinstance(db_incremental_field_last_value, dt.datetime):
        last = db_incremental_field_last_value.date()
    elif isinstance(db_incremental_field_last_value, dt.date):
        last = db_incremental_field_last_value
    else:
        last = dt.date.fromisoformat(str(db_incremental_field_last_value)[:10])

    start = max(last - dt.timedelta(days=LOOKBACK_DAYS), _initial_start_date(today))
    return start, end_date


def _iter_chunks(start: dt.date, end: dt.date) -> collections.abc.Iterator[tuple[dt.date, dt.date]]:
    current = start
    while current <= end:
        chunk_end = min(current + dt.timedelta(days=CHUNK_DAYS - 1), end)
        yield current, chunk_end
        current = chunk_end + dt.timedelta(days=1)


def google_analytics_source(
    config: GoogleAnalyticsSourceConfig,
    resource_name: str,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GoogleAnalyticsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if resource_name not in GOOGLE_ANALYTICS_REPORT_SCHEMAS:
        raise ValueError(f"Unknown Google Analytics schema: {resource_name}")

    schema = GOOGLE_ANALYTICS_REPORT_SCHEMAS[resource_name]
    dimensions = schema["dimensions"]
    metrics = schema["metrics"]
    primary_keys = list(schema["primary_key"])

    name = NamingConvention.normalize_identifier(resource_name)

    def get_rows() -> collections.abc.Iterator[list[dict[str, Any]]]:
        today = _today()
        start_date, end_date = _resolve_window(
            today,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )

        resume_chunk_start: str | None = None
        resume_offset = 0
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                resume_chunk_start = resume.chunk_start
                resume_offset = resume.offset
                # Re-chunk from the saved chunk start so chunk boundaries always line
                # up with the saved offset, even if the incremental window start moved
                # between attempts. If the saved date is past end_date, no chunks run.
                start_date = max(start_date, dt.date.fromisoformat(resume_chunk_start))

        session = google_analytics_session(config.google_analytics_integration_id, team_id)

        for chunk_start, chunk_end in _iter_chunks(start_date, end_date):
            chunk_start_iso = chunk_start.isoformat()
            # The saved offset only applies to the exact chunk it was saved for.
            offset = resume_offset if chunk_start_iso == resume_chunk_start else 0

            while True:
                payload = _run_report(
                    session=session,
                    property_id=config.property_id,
                    start_date=chunk_start_iso,
                    end_date=chunk_end.isoformat(),
                    dimensions=dimensions,
                    metrics=metrics,
                    offset=offset,
                )
                rows = _rows_to_dicts(payload)
                if not rows:
                    break

                yield rows

                next_offset = offset + len(rows)
                row_count = payload.get("rowCount", 0)
                if next_offset >= row_count:
                    # Chunk exhausted — persist the next chunk's starting state so a
                    # restart picks up there with offset=0.
                    next_chunk_iso = (chunk_end + dt.timedelta(days=1)).isoformat()
                    resumable_source_manager.save_state(
                        GoogleAnalyticsResumeConfig(chunk_start=next_chunk_iso, offset=0)
                    )
                    break

                resumable_source_manager.save_state(
                    GoogleAnalyticsResumeConfig(chunk_start=chunk_start_iso, offset=next_offset)
                )
                offset = next_offset

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["date"],
    )
