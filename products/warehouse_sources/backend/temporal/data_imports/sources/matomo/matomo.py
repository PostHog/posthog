import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.settings import (
    DEFAULT_BACKFILL_DAYS,
    MATOMO_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
    VISIT_FINALITY_WINDOW_SECONDS,
)

REQUEST_TIMEOUT_SECONDS = 120
# Matomo Cloud caps Live methods at 200/min and reports at 350/min per IP.
REQUEST_THROTTLE_SECONDS = 0.35
MAX_RETRY_ATTEMPTS = 5
VISITS_PAGE_SIZE = 1000


class MatomoRetryableError(Exception):
    pass


@dataclasses.dataclass
class MatomoResumeConfig:
    # Visits: the serverTimestamp cursor of the next minTimestamp request.
    # Reports: the next unfetched day (yyyy-mm-dd).
    min_timestamp: Optional[int] = None
    next_date: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s)."""
    host = host.strip()
    if not host:
        raise ValueError("Matomo host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Matomo host: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _get_session(api_token: str) -> requests.Session:
    # `host` is user-supplied, so pin redirects off: validation and the
    # outbound request must stay on the same target (SSRF defense-in-depth).
    return make_tracked_session(redact_values=(api_token,), allow_redirects=False)


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def validate_credentials(host: str, site_id: str, api_token: str) -> bool:
    """Confirm the instance is reachable and the token can read the site."""
    try:
        response = _get_session(api_token).post(
            f"{normalize_host(host)}/index.php",
            data={
                "module": "API",
                "method": "SitesManager.getSiteFromId",
                "idSite": site_id,
                "format": "JSON",
                # The token goes in the POST body, never the query string, so
                # it can't leak into server access logs.
                "token_auth": api_token,
            },
            timeout=15,
        )
        if response.status_code != 200:
            return False
        body = response.json()
        return not (isinstance(body, dict) and body.get("result") == "error")
    except Exception:
        return False


def get_rows(
    host: str,
    site_id: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MatomoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MATOMO_ENDPOINTS[endpoint]
    session = _get_session(api_token)
    api_url = f"{normalize_host(host)}/index.php"

    @retry(
        retry=retry_if_exception_type((MatomoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def call(method: str, extra: dict[str, Any]) -> Any:
        # Throttle every call, including tenacity retries, so a retry storm
        # can't blow past Matomo's per-IP rate limit on top of the backoff.
        time.sleep(REQUEST_THROTTLE_SECONDS)
        response = session.post(
            api_url,
            data={
                "module": "API",
                "method": method,
                "idSite": site_id,
                "format": "JSON",
                "token_auth": api_token,
                **extra,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise MatomoRetryableError(f"Matomo API error (retryable): status={response.status_code}")

        if not response.ok:
            logger.error(f"Matomo API error: status={response.status_code}, body={response.text[:500]}")
            response.raise_for_status()

        body = response.json()
        # Matomo reports application errors as 200s with a result envelope.
        if isinstance(body, dict) and body.get("result") == "error":
            raise ValueError(f"Matomo API error: {body.get('message')}")
        return body

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.kind == "visits":
        min_timestamp = 0
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            try:
                min_timestamp = int(float(db_incremental_field_last_value))
            except (TypeError, ValueError):
                min_timestamp = 0
        if resume_config is not None and resume_config.min_timestamp is not None:
            min_timestamp = max(min_timestamp, resume_config.min_timestamp)
            logger.debug(f"Matomo: resuming visits from minTimestamp {min_timestamp}")

        # Defer visits that may still be in progress so their action list is
        # complete when stored; they're picked up by the next sync instead.
        finality_cutoff = int(datetime.now(tz=UTC).timestamp()) - VISIT_FINALITY_WINDOW_SECONDS

        today = datetime.now(tz=UTC).date()
        if min_timestamp > 0:
            range_start = datetime.fromtimestamp(min_timestamp, tz=UTC).date()
        else:
            range_start = today - timedelta(days=DEFAULT_BACKFILL_DAYS)

        while True:
            batch = call(
                config.method,
                {
                    "period": "range",
                    "date": f"{range_start.isoformat()},{today.isoformat()}",
                    "filter_limit": VISITS_PAGE_SIZE,
                    "filter_sort_order": "asc",
                    "minTimestamp": min_timestamp,
                },
            )
            if not isinstance(batch, list):
                return
            visits = [row for row in batch if isinstance(row, dict)]

            final_visits = []
            for visit in visits:
                ts = visit.get("serverTimestamp")
                if isinstance(ts, (int, float)) and ts > finality_cutoff:
                    continue
                final_visits.append(visit)

            if final_visits:
                yield final_visits

            if len(visits) < VISITS_PAGE_SIZE or not final_visits:
                return

            timestamps = [
                int(v["serverTimestamp"]) for v in final_visits if isinstance(v.get("serverTimestamp"), (int, float))
            ]
            if not timestamps:
                return
            next_min_timestamp = max(timestamps)
            # minTimestamp is inclusive: boundary visits at the max second get
            # refetched next page and deduped on idVisit (fine). But if a full
            # page's visits all fall in a single second, advancing to that
            # second returns the same page forever, so step one second past it
            # to guarantee progress. The only loss is overflow beyond
            # VISITS_PAGE_SIZE visits within that one second — an accepted
            # tradeoff against stalling the sync indefinitely.
            if next_min_timestamp <= min_timestamp or min(timestamps) == next_min_timestamp:
                next_min_timestamp = next_min_timestamp + 1
            min_timestamp = next_min_timestamp
            # Save state AFTER yielding so a crash re-yields the in-flight
            # batch (merge dedupes on idVisit).
            resumable_source_manager.save_state(MatomoResumeConfig(min_timestamp=min_timestamp))

    # Per-day report walk, oldest-first. Recent days re-archive, so
    # incremental runs re-pull a trailing lookback window.
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=DEFAULT_BACKFILL_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)

    if resume_config is not None and resume_config.next_date:
        resumed = _to_date(resume_config.next_date)
        if resumed is not None and resumed > start:
            start = resumed
            logger.debug(f"Matomo: resuming {endpoint} from {start.isoformat()}")

    day = start
    while day <= today:
        body = call(config.method, {"period": "day", "date": day.isoformat(), "filter_limit": -1})
        rows = body if isinstance(body, list) else ([body] if isinstance(body, dict) and body else [])
        rows = [{**row, "_date": day.isoformat()} for row in rows if isinstance(row, dict)]
        if rows:
            yield rows

        day = day + timedelta(days=1)
        if day <= today:
            # Save state AFTER yielding so a crash re-yields the in-flight day.
            resumable_source_manager.save_state(MatomoResumeConfig(next_date=day.isoformat()))


def matomo_source(
    host: str,
    site_id: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MatomoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MATOMO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            site_id=site_id,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        # Visits are fetched ascending by serverTimestamp; report days are
        # walked oldest-first — both cursors only move forward.
        sort_mode="asc",
    )
