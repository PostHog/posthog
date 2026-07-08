import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    SPARKPOST_ENDPOINTS,
    SparkPostEndpointConfig,
)

# SparkPost runs fully independent US and EU stacks that do not share data; the user picks which one
# their account lives on. The set is a fixed allow-list, so the host can't be retargeted at an
# arbitrary server.
SPARKPOST_HOSTS = {
    "us": "https://api.sparkpost.com",
    "eu": "https://api.eu.sparkpost.com",
}
DEFAULT_REGION = "us"

REQUEST_TIMEOUT_SECONDS = 60


class SparkPostRetryableError(Exception):
    pass


@dataclasses.dataclass
class SparkPostResumeConfig:
    next_url: str


def base_url(region: Optional[str]) -> str:
    resolved = (region or DEFAULT_REGION).lower()
    return SPARKPOST_HOSTS.get(resolved, SPARKPOST_HOSTS[DEFAULT_REGION])


def _get_headers(api_key: str) -> dict[str, str]:
    # SparkPost authenticates with the API key passed verbatim in the Authorization header (no
    # "Bearer" prefix).
    return {
        "Authorization": api_key,
        "Accept": "application/json",
    }


def _format_from(value: Any) -> str:
    """Format an incremental cursor value for SparkPost's ``from`` filter.

    SparkPost's Events Search API expects ``YYYY-MM-DDTHH:MM`` and treats it as UTC by default. We
    truncate to the minute (the finest granularity the filter accepts); ``from`` is inclusive, so
    the boundary event is re-fetched and deduped on ``event_id`` by the merge.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        # The stored watermark can come back as an ISO 8601 string; parse it so we still emit the
        # ``YYYY-MM-DDTHH:MM`` SparkPost wants rather than passing e.g. ``2026-01-01T00:00:00Z``
        # through verbatim (which the API rejects). Normalize a trailing ``Z`` for fromisoformat.
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M")


def validate_credentials(region: Optional[str], api_key: str) -> tuple[bool, str | None]:
    """Validate SparkPost credentials with a single cheap probe against ``/api/v1/account``."""
    url = f"{base_url(region)}/api/v1/account"
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), timeout=10)
        if response.status_code == 200:
            return True, None
        # 403 means the key authenticated but lacks the ``Account`` scope this probe uses. The key
        # is genuine, and a user who only grants the per-data-type read scopes (as our caption
        # suggests) shouldn't be blocked from connecting — real per-endpoint scope gaps surface at
        # sync time via get_non_retryable_errors. Only 401 is a definitively bad key.
        if response.status_code == 403:
            return True, None
        if response.status_code == 401:
            return False, "Invalid SparkPost API key. Check the API key and selected region, then try again."
        return False, f"SparkPost credential validation failed (status {response.status_code})."
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _build_initial_params(
    config: SparkPostEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.pagination == "cursor":
        # ``cursor=initial`` opts the request into SparkPost's cursor-based pagination; we then walk
        # the ``rel: next`` links it returns.
        params["cursor"] = "initial"
        params["per_page"] = config.per_page

    if config.timestamp_filter_param:
        # Continue from the stored watermark on incremental runs; otherwise seed the first sync with
        # the lookback window (bounded by SparkPost's 10-day event retention).
        if should_use_incremental_field and db_incremental_field_last_value:
            cutoff: Any = db_incremental_field_last_value
        elif config.default_lookback_days:
            cutoff = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        else:
            cutoff = None

        if cutoff is not None:
            params[config.timestamp_filter_param] = _format_from(cutoff)

    return params


def _build_initial_url(host: str, config: SparkPostEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{host}{config.path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _extract_items(response_json: Any, config: SparkPostEndpointConfig) -> list[dict[str, Any]]:
    if isinstance(response_json, dict):
        items = response_json.get(config.data_path, [])
        return items if isinstance(items, list) else []
    return []


def _is_same_host(url: str, host: str) -> bool:
    """True only for ``https`` URLs whose netloc matches the resolved SparkPost API host."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(host).netloc


def _compute_next_url(config: SparkPostEndpointConfig, response_json: Any, host: str) -> str | None:
    if config.pagination != "cursor":
        return None

    # SparkPost returns pagination links as a list of ``{"href": ..., "rel": ...}`` objects; the
    # ``next`` href is a path relative to the API host (e.g. ``/api/v1/events/message?cursor=...``).
    links = response_json.get("links") if isinstance(response_json, dict) else None
    if not isinstance(links, list):
        return None

    for link in links:
        if isinstance(link, dict) and link.get("rel") == "next":
            href = link.get("href")
            if not isinstance(href, str) or not href:
                return None
            # ``urljoin`` resolves a relative path against the host and leaves an absolute URL as-is.
            # Either way we re-pin it to the resolved host so a tampered response can't redirect our
            # authenticated request at an internal address (SSRF) and leak the API key.
            resolved = urljoin(f"{host}/", href)
            return resolved if _is_same_host(resolved, host) else None
    return None


def get_rows(
    region: Optional[str],
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SparkPostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SPARKPOST_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    host = base_url(region)
    # One tracked session reused across pages and retries; the API key is redacted from logged URLs
    # and captured samples.
    session = make_tracked_session(headers=headers, redact_values=(api_key,))

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        # Guard the persisted resume URL too — only ever saved from _compute_next_url (host-pinned),
        # but re-check so a tampered Redis state can't redirect our authenticated request.
        if not _is_same_host(url, host):
            raise ValueError(f"SparkPost resume state contains an unexpected URL: {url!r}")
        logger.debug(f"SparkPost: resuming from URL: {url}")
    else:
        url = _build_initial_url(host, config, params)

    @retry(
        retry=retry_if_exception_type((SparkPostRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        # SparkPost applies dynamic rate limiting, returning 429 with guidance to back off 1-5s.
        if response.status_code == 429 or response.status_code >= 500:
            raise SparkPostRetryableError(
                f"SparkPost API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"SparkPost API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = _extract_items(data, config)
        if not items:
            break

        yield items

        next_url = _compute_next_url(config, data, host)
        if not next_url:
            break

        # Save state AFTER yielding the batch — a crash re-yields the last batch (merge dedupes on
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(SparkPostResumeConfig(next_url=next_url))
        url = next_url


def sparkpost_source(
    region: Optional[str],
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SparkPostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SPARKPOST_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
