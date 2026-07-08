import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import DIXA_ENDPOINTS

DIXA_MAIN_BASE_URL = "https://dev.dixa.io/v1"
DIXA_EXPORT_BASE_URL = "https://exports.dixa.io/v1"
# Hosts we will send the Bearer token to. meta.next pagination URLs and
# resumed state are validated against this so a tampered/absolute URL can't
# exfiltrate the token to an attacker-controlled host.
DIXA_MAIN_HOST = urlparse(DIXA_MAIN_BASE_URL).netloc
# Export queries cannot span more than 31 days; stay safely under.
EXPORT_WINDOW_MS = 30 * 24 * 60 * 60 * 1000
# Dixa has no created-before-2015 data; full exports start here.
EXPORT_EPOCH_MS = int(datetime(2015, 1, 1, tzinfo=UTC).timestamp() * 1000)
# conversation_export allows only 10 requests/minute per org token.
EXPORT_REQUEST_INTERVAL_SECONDS = 6.5
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5


class DixaRetryableError(Exception):
    pass


@dataclasses.dataclass
class DixaResumeConfig:
    # Export streams persist the start of the next time window (Unix ms); main
    # API streams persist the opaque next-page URL from meta.next.
    window_start_ms: Optional[int] = None
    next_url: Optional[str] = None


def _get_session(api_token: str) -> requests.Session:
    # allow_redirects=False so a redirect response can't reroute the Bearer
    # token to a different host.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}"},
        redact_values=(api_token,),
        allow_redirects=False,
    )


def _is_dixa_main_host(url: str) -> bool:
    return urlparse(url).netloc == DIXA_MAIN_HOST


def _to_ms(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to Unix milliseconds for export filters."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def validate_credentials(api_token: str) -> tuple[bool, Optional[str]]:
    """Probe the API token with a cheap agents listing.

    Returns ``(is_valid, error_message)``. Only an explicit auth rejection
    (401/403) is reported as an invalid token — transient failures (429, 5xx,
    network errors) get a distinct message so a working token isn't mislabelled
    as wrong when Dixa is merely unreachable.
    """
    try:
        response = _get_session(api_token).get(
            f"{DIXA_MAIN_BASE_URL}/agents",
            timeout=10,
        )
    except Exception:
        return False, "Could not reach Dixa to validate the API token. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Dixa API token"
    return (
        False,
        f"Dixa returned an unexpected response ({response.status_code}) while validating the API token. Please try again.",
    )


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DixaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DIXA_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((DixaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def fetch(url: str) -> Any:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DixaRetryableError(f"Dixa API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Dixa API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.surface == "export":
        # The Exports API takes a mandatory time window (max 31 days) and
        # returns the whole window as one JSON array — walk windows forward
        # from the watermark (or Dixa's epoch on a full export).
        if resume_config is not None and resume_config.window_start_ms is not None:
            window_start = resume_config.window_start_ms
            logger.debug(f"Dixa: resuming {endpoint} from window start {window_start}")
        elif should_use_incremental_field:
            window_start = _to_ms(db_incremental_field_last_value) or EXPORT_EPOCH_MS
        else:
            window_start = EXPORT_EPOCH_MS

        is_first_window = True
        while window_start < _now_ms():
            window_end = min(window_start + EXPORT_WINDOW_MS, _now_ms())
            params = {"updated_after": window_start, "updated_before": window_end}
            # conversation_export is rate limited to 10 req/min — space requests
            # out, but don't penalise the first request of the run (the limit
            # hasn't been touched yet).
            if not is_first_window:
                time.sleep(EXPORT_REQUEST_INTERVAL_SECONDS)
            is_first_window = False
            data = fetch(f"{DIXA_EXPORT_BASE_URL}{config.path}?{urlencode(params)}")
            items = data if isinstance(data, list) else []

            if items:
                yield items

            window_start = window_end
            # Save state AFTER yielding the window so a crash re-yields it
            # (merge dedupes on primary key) rather than skipping it.
            resumable_source_manager.save_state(DixaResumeConfig(window_start_ms=window_start))
        return

    if resume_config is not None and resume_config.next_url is not None and _is_dixa_main_host(resume_config.next_url):
        url: str = resume_config.next_url
        logger.debug(f"Dixa: resuming {endpoint} from URL: {url}")
    else:
        url = f"{DIXA_MAIN_BASE_URL}{config.path}"

    while True:
        data = fetch(url)
        items = data.get("data", []) if isinstance(data, dict) else []
        items = items or []

        if items:
            yield items

        next_link = (data.get("meta") or {}).get("next") if isinstance(data, dict) else None
        if not next_link or not items:
            break

        # meta.next can be a relative path; absolutize against the main host.
        next_url = urljoin(DIXA_MAIN_BASE_URL, next_link)
        # urljoin returns an absolute meta.next unchanged, so a tampered URL
        # pointing elsewhere would otherwise receive the Bearer token. Stop
        # paginating if it doesn't resolve to the Dixa main host.
        if not _is_dixa_main_host(next_url):
            logger.warning(f"Dixa: meta.next resolved to unexpected host, stopping pagination: {next_url}")
            break
        resumable_source_manager.save_state(DixaResumeConfig(next_url=next_url))
        url = next_url


def dixa_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DixaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DIXA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Export windows advance chronologically, so the watermark (max
        # updated_at per batch) only moves forward.
        sort_mode="asc",
    )
