import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    DATADOG_ENDPOINTS,
    DatadogEndpointConfig,
    TimestampFormat,
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


class DatadogFanOutLimitError(Exception):
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


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        # The month, hour and epoch filters cannot pass a raw string through the way an ISO filter
        # can, so parse it here rather than sending Datadog a value it rejects.
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a ``Z`` suffix for Datadog filters."""
    dt = _coerce_datetime(value)
    if dt is None:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_filter_value(value: Any, timestamp_format: TimestampFormat) -> str:
    """Encode a cursor value the way the target endpoint's time filter expects it."""
    if timestamp_format == "iso_ms":
        return _format_datetime(value)

    dt = _coerce_datetime(value)
    if dt is None:
        return str(value)
    if timestamp_format == "month":
        return dt.strftime("%Y-%m")
    if timestamp_format == "hour":
        return dt.strftime("%Y-%m-%dT%H")
    return str(int(dt.timestamp()))


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

    params.update(config.static_params)

    if config.pagination != "none" and config.page_size_param:
        params[config.page_size_param] = config.page_size
    if config.pagination == "offset" and config.offset_param:
        params[config.offset_param] = 0
    if config.pagination == "page" and config.page_index_param:
        params[config.page_index_param] = 0

    if config.sort_param:
        params["sort"] = config.sort_param

    now = datetime.now(UTC)

    if config.timestamp_filter_param:
        # Continue from the stored watermark on incremental runs; otherwise seed the first sync
        # with the lookback window so we don't fall back to Datadog's ``now-15m`` default.
        if should_use_incremental_field and db_incremental_field_last_value:
            cutoff: Any = db_incremental_field_last_value
        elif config.default_lookback_days:
            cutoff = now - timedelta(days=config.default_lookback_days)
        else:
            cutoff = None

        if cutoff is not None:
            params[config.timestamp_filter_param] = _format_filter_value(cutoff, config.timestamp_filter_format)

    if config.window_end_param:
        params[config.window_end_param] = _format_filter_value(now, config.timestamp_filter_format)

    return params


def _build_initial_url(host: str, path: str, params: dict[str, Any]) -> str:
    url = f"{host}{path}"
    if not params:
        return url
    # Keep the JSON:API bracket syntax (``page[limit]``) literal; Datadog expects it.
    return f"{url}?{urlencode(params, safe='[]')}"


def _extract_items(response_json: Any, config: DatadogEndpointConfig) -> list[dict[str, Any]]:
    raw: Any
    if config.data_path is None:
        raw = response_json if isinstance(response_json, list) else []
    elif isinstance(response_json, dict):
        raw = response_json.get(config.data_path, [])
    else:
        raw = []

    if config.single_object:
        return [raw] if isinstance(raw, dict) else []
    if not isinstance(raw, list):
        return []
    if config.scalar_field:
        return [{config.scalar_field: value} for value in raw]
    return raw


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

    if config.pagination == "record_id":
        # The usage-metering endpoints hand back an opaque record id instead of a URL, and it is
        # the only termination signal — a short page does not mean the walk is over.
        next_record_id: Any = response_json
        for key in config.record_id_path:
            next_record_id = next_record_id.get(key) if isinstance(next_record_id, dict) else None
        if not isinstance(next_record_id, str) or not next_record_id or not config.record_id_param:
            return None
        parsed = urlparse(current_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query[config.record_id_param] = next_record_id
        return urlunparse(parsed._replace(query=urlencode(query, safe="[]")))

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


def _make_fetcher(
    session: requests.Session,
    logger: FilteringBoundLogger,
) -> Callable[..., Any]:
    @retry(
        retry=retry_if_exception_type((DatadogRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str, allow_missing: bool = False) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        # 408 is a transient request timeout on Datadog's side; retry it like 429/5xx rather than
        # letting it raise_for_status() into a fatal, non-retried HTTPError.
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise DatadogRetryableError(f"Datadog API error (retryable): status={response.status_code}, url={page_url}")

        if allow_missing and response.status_code == 404:
            return None

        if not response.ok:
            logger.error(f"Datadog API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _walk(
    config: DatadogEndpointConfig,
    start_url: str,
    fetch_page: Callable[..., Any],
    host: str,
    save_state: Callable[[str], None] | None = None,
    allow_missing: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    """Page through one endpoint URL, yielding a normalized batch per response."""
    url = start_url
    while True:
        data = fetch_page(url, allow_missing)
        if data is None:
            return

        items = _extract_items(data, config)
        if items:
            if config.flatten_attributes:
                items = [_flatten_item(item) for item in items]
            yield items

        # An empty page is not the end of the walk: the usage endpoints carry their cursor in
        # `meta` independently of `data`, so only the paginator decides when to stop.
        next_url = _compute_next_url(config, url, data, len(items), host)
        # A cursor the API repeats would otherwise loop this walk forever.
        if not next_url or next_url == url:
            return

        if save_state is not None:
            # Save state AFTER yielding the batch — a crash re-yields the last batch (merge dedupes
            # on primary key) instead of skipping it.
            save_state(next_url)
        url = next_url


def _fan_out_rows(
    config: DatadogEndpointConfig,
    fetch_page: Callable[..., Any],
    host: str,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a parent endpoint and query the child endpoint once per parent id."""
    fan_out = config.parent
    assert fan_out is not None
    parent_config = DATADOG_ENDPOINTS[fan_out.parent_endpoint]
    parent_url = _build_initial_url(
        host,
        parent_config.path,
        _build_initial_params(parent_config, should_use_incremental_field=False, db_incremental_field_last_value=None),
    )

    parents_seen = 0
    for parent_batch in _walk(parent_config, parent_url, fetch_page, host):
        for parent in parent_batch:
            if parents_seen >= fan_out.max_parents:
                # Returning here would write a truncated table that looks like a complete sync.
                raise DatadogFanOutLimitError(
                    f"{config.name} expands one Datadog request per {fan_out.parent_endpoint} record, "
                    f"and this account has more than the {fan_out.max_parents} we sync. "
                    f"Deselect {config.name} to keep the rest of your Datadog tables syncing."
                )
            parents_seen += 1

            parent_id = parent.get(fan_out.parent_id_field)
            if parent_id in (None, ""):
                continue

            child_path = config.path.replace("{parent_id}", quote(str(parent_id), safe=""))
            child_url = _build_initial_url(
                host,
                child_path,
                _build_initial_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None),
            )
            # A parent deleted between the list call and its child call answers 404; skip it
            # rather than failing the whole sync.
            for child_batch in _walk(config, child_url, fetch_page, host, allow_missing=True):
                for row in child_batch:
                    row[fan_out.child_id_field] = parent_id
                yield child_batch


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
    fetch_page = _make_fetcher(session, logger)

    if config.parent is not None:
        # A fan-out position is a parent cursor plus a child page, which the single-URL resume
        # state cannot express, so these endpoints restart from the first parent instead.
        yield from _fan_out_rows(config, fetch_page, host)
        return

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        # Guard the persisted resume URL too — only ever saved from _compute_next_url (host-pinned),
        # but re-check so a tampered Redis state can't redirect our authenticated request.
        if not _is_same_host(url, host):
            raise ValueError(f"Datadog resume state contains an unexpected URL: {url!r}")
        logger.debug(f"Datadog: resuming from URL: {url}")
    else:
        params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)
        url = _build_initial_url(host, config.path, params)

    yield from _walk(
        config,
        url,
        fetch_page,
        host,
        save_state=lambda next_url: resumable_source_manager.save_state(DatadogResumeConfig(next_url=next_url)),
    )


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
        primary_keys=list(config.primary_keys),
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
