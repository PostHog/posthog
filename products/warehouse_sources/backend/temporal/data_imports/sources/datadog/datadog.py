import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    DATADOG_ENDPOINTS,
    DatadogEndpointConfig,
)

# Datadog regional sites. The site selects which API host the credentials are sent to. The set is
# a fixed allow-list, so the host can't be retargeted at an arbitrary server.
DATADOG_SITES = (
    "datadoghq.com",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "datadoghq.eu",
    "ap1.datadoghq.com",
    "ddog-gov.com",
)
DEFAULT_SITE = "datadoghq.com"

REQUEST_TIMEOUT_SECONDS = 60


class DatadogRetryableError(Exception):
    pass


@dataclasses.dataclass
class DatadogResumeConfig:
    next_url: str


def base_url(site: Optional[str]) -> str:
    resolved = site or DEFAULT_SITE
    if resolved not in DATADOG_SITES:
        resolved = DEFAULT_SITE
    return f"https://api.{resolved}"


def _get_headers(api_key: str, app_key: str) -> dict[str, str]:
    return {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a ``Z`` suffix for Datadog filters."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def validate_credentials(site: Optional[str], api_key: str, app_key: str) -> tuple[bool, str | None]:
    """Validate Datadog credentials with a single cheap probe.

    ``/api/v1/validate`` confirms the API key is genuine but does NOT exercise the application key
    (no v1/v2 endpoint validates the app key without reading real data). Missing application-key
    scopes surface at sync time as 403s, handled by ``get_non_retryable_errors``.
    """
    url = f"{base_url(site)}/api/v1/validate"
    try:
        session = make_tracked_session(redact_values=(api_key, app_key))
        response = session.get(url, headers=_get_headers(api_key, app_key), timeout=10)
        if response.status_code == 200:
            return True, None
        if response.status_code in (401, 403):
            return False, "Invalid Datadog API key. Check the API key and selected site, then try again."
        return False, f"Datadog credential validation failed (status {response.status_code})."
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _build_initial_params(
    config: DatadogEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.pagination != "none" and config.page_size_param:
        params[config.page_size_param] = config.page_size
    if config.pagination == "offset" and config.offset_param:
        params[config.offset_param] = 0
    if config.pagination == "page" and config.page_index_param:
        params[config.page_index_param] = 0

    if config.sort_param:
        params["sort"] = config.sort_param

    if config.timestamp_filter_param:
        # Continue from the stored watermark on incremental runs; otherwise seed the first sync
        # with the lookback window so we don't fall back to Datadog's ``now-15m`` default.
        if should_use_incremental_field and db_incremental_field_last_value:
            cutoff: Any = db_incremental_field_last_value
        elif config.default_lookback_days:
            cutoff = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        else:
            cutoff = None

        if cutoff is not None:
            params[config.timestamp_filter_param] = _format_datetime(cutoff)

    return params


def _build_initial_url(host: str, config: DatadogEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{host}{config.path}"
    if not params:
        return url
    # Keep the JSON:API bracket syntax (``page[limit]``) literal; Datadog expects it.
    return f"{url}?{urlencode(params, safe='[]')}"


def _extract_items(response_json: Any, config: DatadogEndpointConfig) -> list[dict[str, Any]]:
    if config.data_path is None:
        return response_json if isinstance(response_json, list) else []
    if isinstance(response_json, dict):
        items = response_json.get(config.data_path, [])
        return items if isinstance(items, list) else []
    return []


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Lift a v2 JSON:API record's ``attributes`` object to the root, keeping ``id``/``type``."""
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        item.pop("attributes")
        for key, value in attributes.items():
            item.setdefault(key, value)
    return item


def _is_same_host(url: str, host: str) -> bool:
    """True only for ``https`` URLs whose netloc matches the resolved Datadog API host."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(host).netloc


def _compute_next_url(
    config: DatadogEndpointConfig,
    current_url: str,
    response_json: Any,
    item_count: int,
    host: str,
) -> str | None:
    if config.pagination == "cursor":
        links = response_json.get("links") if isinstance(response_json, dict) else None
        next_link = links.get("next") if isinstance(links, dict) else None
        # Only follow pagination URLs that stay on the resolved Datadog API host, so a tampered or
        # compromised API response can't point our authenticated request at an internal address
        # (SSRF) and leak the DD-API-KEY / DD-APPLICATION-KEY headers.
        if isinstance(next_link, str) and _is_same_host(next_link, host):
            return next_link
        return None

    # Numeric pagination: a short page means we've reached the end.
    if item_count < config.page_size:
        return None

    parsed = urlparse(current_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if config.pagination == "page" and config.page_index_param:
        current = int(query.get(config.page_index_param, 0))
        query[config.page_index_param] = str(current + 1)
    elif config.pagination == "offset" and config.offset_param:
        current = int(query.get(config.offset_param, 0))
        query[config.offset_param] = str(current + config.page_size)
    else:
        return None

    return urlunparse(parsed._replace(query=urlencode(query, safe="[]")))


def get_rows(
    site: Optional[str],
    api_key: str,
    app_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DatadogResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DATADOG_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, app_key)
    host = base_url(site)
    # One tracked session reused across pages and retries; credentials are redacted from logged
    # URLs and captured samples.
    session = make_tracked_session(headers=headers, redact_values=(api_key, app_key))

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        # Guard the persisted resume URL too — only ever saved from _compute_next_url (host-pinned),
        # but re-check so a tampered Redis state can't redirect our authenticated request.
        if not _is_same_host(url, host):
            raise ValueError(f"Datadog resume state contains an unexpected URL: {url!r}")
        logger.debug(f"Datadog: resuming from URL: {url}")
    else:
        url = _build_initial_url(host, config, params)

    @retry(
        retry=retry_if_exception_type((DatadogRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DatadogRetryableError(f"Datadog API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Datadog API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = _extract_items(data, config)
        if not items:
            break

        if config.flatten_attributes:
            items = [_flatten_item(item) for item in items]

        yield items

        next_url = _compute_next_url(config, url, data, len(items), host)
        if not next_url:
            break

        # Save state AFTER yielding the batch — a crash re-yields the last batch (merge dedupes on
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(DatadogResumeConfig(next_url=next_url))
        url = next_url


def datadog_source(
    site: Optional[str],
    api_key: str,
    app_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DatadogResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DATADOG_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            site=site,
            api_key=api_key,
            app_key=app_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
