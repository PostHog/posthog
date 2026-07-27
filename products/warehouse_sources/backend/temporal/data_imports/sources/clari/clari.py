import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.settings import CLARI_BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 120
# ~10 req/s general limit; back off on 429.
MAX_RETRY_ATTEMPTS = 5
AUDIT_PAGE_LIMIT = 1000
# Export jobs usually finish in minutes; the per-attempt poll budget is capped
# so a stuck job surfaces as a retryable error instead of hanging the activity.
EXPORT_POLL_INTERVAL_SECONDS = 15
EXPORT_POLL_MAX_ATTEMPTS = 60


class ClariRetryableError(Exception):
    pass


@dataclasses.dataclass
class ClariResumeConfig:
    # Forecast: the in-flight export job to re-poll instead of creating a new
    # one (exports are quota-limited to ~1000 per rolling 30 days). Audit
    # events: the nextLink URL of the next unfetched page.
    job_id: Optional[str] = None
    next_link: Optional[str] = None


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"apikey": api_key}, redact_values=(api_key,))


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key works with a cheap audit-events probe."""
    try:
        response = _get_session(api_key).get(
            f"{CLARI_BASE_URL}/audit/events?limit=1",
            timeout=15,
        )
        return response.status_code == 200
    except Exception:
        return False


def _make_fetcher(session: requests.Session, logger: FilteringBoundLogger):
    @retry(
        retry=retry_if_exception_type((ClariRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(method: str, url: str, json_body: Optional[dict[str, Any]] = None) -> requests.Response:
        response = session.request(method, url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise ClariRetryableError(f"Clari API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Clari API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response

    return fetch


def get_audit_events(
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClariResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_key)
    fetch = _make_fetcher(session, logger)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_link:
        url: Optional[str] = resume_config.next_link
        logger.debug("Clari: resuming audit_events from saved nextLink")
    else:
        params: dict[str, Any] = {"limit": AUDIT_PAGE_LIMIT}
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            params["dateFrom"] = _format_timestamp(db_incremental_field_last_value)
        url = f"{CLARI_BASE_URL}/audit/events?{urlencode(params)}"

    while url:
        data = fetch("GET", url).json()
        items = data.get("items") or data.get("activities") or []

        if items:
            yield items

        url = data.get("nextLink") or None
        if url:
            # Save state AFTER yielding so a crash re-yields the in-flight page.
            resumable_source_manager.save_state(ClariResumeConfig(next_link=url))


def _extract_result_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("data", "rows", "records", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [data]
    return []


def get_forecast(
    api_key: str,
    forecast_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClariResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_key)
    fetch = _make_fetcher(session, logger)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    job_id = resume_config.job_id if resume_config is not None else None
    if job_id:
        logger.debug(f"Clari: re-polling existing forecast export job {job_id}")

    if not job_id:
        create_body = fetch(
            "POST",
            f"{CLARI_BASE_URL}/export/forecast/{quote(forecast_id)}",
            json_body={"exportFormat": "JSON"},
        ).json()
        job_id = create_body.get("jobId") or (create_body.get("job") or {}).get("id")
        if not job_id:
            raise ValueError(f"Clari export job creation returned no jobId: {create_body}")
        # Persist immediately — exports are quota-limited, so a retried
        # activity must re-poll this job rather than create another.
        resumable_source_manager.save_state(ClariResumeConfig(job_id=job_id))

    status = None
    for _attempt in range(EXPORT_POLL_MAX_ATTEMPTS):
        job_body = fetch("GET", f"{CLARI_BASE_URL}/export/jobs/{quote(job_id)}").json()
        job = job_body.get("job") if isinstance(job_body.get("job"), dict) else job_body
        status = job["status"]

        if status == "DONE":
            break
        if status in ("FAILED", "CANCELLED", "ABORTED"):
            # Don't re-poll a dead job on retry.
            resumable_source_manager.save_state(ClariResumeConfig(job_id=None))
            raise ValueError(f"Clari forecast export job {job_id} ended with status {status}")

        time.sleep(EXPORT_POLL_INTERVAL_SECONDS)
    else:
        raise ClariRetryableError(f"Clari forecast export job {job_id} still {status} after polling budget")

    results = fetch("GET", f"{CLARI_BASE_URL}/export/jobs/{quote(job_id)}/results").json()
    rows = _extract_result_rows(results)
    if rows:
        yield rows


def clari_source(
    api_key: str,
    forecast_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClariResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint == "audit_events":
        return SourceResponse(
            name=endpoint,
            items=lambda: get_audit_events(
                api_key=api_key,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ),
            # Audit events carry no unique id — dedupe on the natural composite.
            primary_keys=["eventTimestamp", "actorId", "sessionId", "event"],
            partition_count=1,
            partition_size=1,
            # Result ordering is undocumented, so only commit the watermark
            # once a sync completes.
            sort_mode="desc",
            has_duplicate_primary_keys=True,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: get_forecast(
            api_key=api_key,
            forecast_id=forecast_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        # Snapshot-style export rows have no identifier; the table fully
        # refreshes each sync.
        primary_keys=None,
        partition_count=1,
        partition_size=1,
    )
