from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import (
    FASTLY_ENDPOINTS,
    FastlyEndpointConfig,
)

FASTLY_BASE_URL = "https://api.fastly.com"

# Fastly caps read requests at ~6,000/minute per token. `/service` supports page-number pagination;
# the account's service count is small in practice, so a large page keeps the round-trip count down.
SERVICE_PAGE_SIZE = 100

# ACL entries and dictionary items page the same way, and both accept up to 100 records per page.
CHILD_PAGE_SIZE = 100

# `/billing/v3/invoices` caps `limit` at 200.
INVOICE_PAGE_LIMIT = 200

# The usage metrics API rejects a window longer than three months, so ask for the three ending now.
USAGE_METRICS_MONTHS = 3


class FastlyRetryableError(Exception):
    pass


class FastlyPaginationError(Exception):
    pass


@frozen
class FastlyResumeConfig:
    # Next page URL for the paginated top-level `services` list.
    next_url: str | None = None
    # Bookmark for fan-out endpoints: the service we were processing when state was saved. On resume
    # we restart at this service and re-yield its rows (merge dedupes on the primary key).
    service_id: str | None = None
    # Opaque next-page cursor for the /billing/v3 endpoints, with the request it continues. A cursor
    # only continues the request that produced it, and the usage metrics window moves with the month.
    cursor: str | None = None
    cursor_request: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"Fastly-Key": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            FastlyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # 429 carries rate-limit reset headers; 5xx are transient. Both are retryable.
    if response.status_code == 429 or response.status_code >= 500:
        raise FastlyRetryableError(f"Fastly API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Fastly API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _next_page_url(response: requests.Response) -> str | None:
    """Fastly signals the next page of `/service` via a standard `Link: <...>; rel="next"` header."""
    return response.links.get("next", {}).get("url")


def validate_credentials(api_key: str) -> bool:
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{FASTLY_BASE_URL}/current_user", headers=_get_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except requests.RequestException:
        # A network blip / timeout at source-create can't confirm the token, so report it as invalid
        # rather than crashing setup. Non-request errors are unexpected and left to propagate.
        return False


def _ensure_id(row: dict[str, Any], field: str, value: str) -> dict[str, Any]:
    """Fastly's nested objects already carry their parent identifiers, but inject them defensively so
    a composite primary key is never missing a parent."""
    if not row.get(field):
        row = {**row, field: value}
    return row


def _ensure_service_id(row: dict[str, Any], service_id: str) -> dict[str, Any]:
    return _ensure_id(row, "service_id", service_id)


def _iter_linked_pages(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[requests.Response]:
    """Walk a Link-header paginated Fastly endpoint, yielding each page's response."""
    while True:
        response = _fetch(session, url, headers, logger)
        yield response
        next_url = _next_page_url(response)
        if not next_url:
            return
        # A next link that points at the page just read would loop forever and re-yield its rows.
        if next_url == url:
            raise FastlyPaginationError(f"Fastly returned an unchanged next page link for {url}")
        url = next_url


def _next_cursor(payload: dict[str, Any]) -> str | None:
    """Read the next-page cursor from a /billing/v3 response. Invoices carry `meta` at the top level
    while the usage metrics response nests it under `data`, so check both rather than assume one."""
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        data = payload.get("data")
        meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, str) and cursor else None


def _request_fingerprint(path: str, params: dict[str, Any]) -> str:
    return _build_url(path, dict(sorted(params.items())))


def _usage_metrics_window(today: datetime | None = None) -> dict[str, str]:
    """The `YYYY-MM` window covering the current month and the two before it."""
    now = today or datetime.now(tz=UTC)
    end_index = now.year * 12 + now.month - 1
    start_index = end_index - (USAGE_METRICS_MONTHS - 1)
    return {
        "start_month": f"{start_index // 12:04d}-{start_index % 12 + 1:02d}",
        "end_month": f"{end_index // 12:04d}-{end_index % 12 + 1:02d}",
    }


def _flatten_usage_metrics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a usage metrics page into one row per (usage type, service). Fastly's own spec models
    `data` as a single usage-type block; live responses may return a list of them, so accept both."""
    data = payload.get("data")
    blocks = data if isinstance(data, list) else [data] if isinstance(data, dict) else []

    rows: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        usage_type = {key: value for key, value in block.items() if key not in ("details", "meta")}
        for detail in block.get("details") or []:
            if isinstance(detail, dict):
                rows.append({**usage_type, **detail})
    return rows


def _iter_services(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    """Page through GET /service, yielding each service object. Used to drive fan-out endpoints."""
    url = _build_url(f"{FASTLY_BASE_URL}/service", {"per_page": SERVICE_PAGE_SIZE})
    while True:
        response = _fetch(session, url, headers, logger)
        items = response.json()
        if isinstance(items, list):
            yield from items
        next_url = _next_page_url(response)
        if not next_url:
            break
        url = next_url


def _active_version_number(
    session: requests.Session, service_id: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> int | None:
    """Resolve the version to read version-scoped resources from: the active version, else the highest
    version number. Fastly config resources are version-scoped, so syncing the active version reflects
    the service's current production configuration."""
    response = _fetch(session, f"{FASTLY_BASE_URL}/service/{service_id}/version", headers, logger)
    versions = response.json()
    if not isinstance(versions, list):
        return None

    active = [v["number"] for v in versions if isinstance(v, dict) and v.get("active") and "number" in v]
    if active:
        return max(active)

    numbers = [v["number"] for v in versions if isinstance(v, dict) and isinstance(v.get("number"), int)]
    return max(numbers) if numbers else None


def _get_object_rows(
    session: requests.Session, config: FastlyEndpointConfig, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    response = _fetch(session, f"{FASTLY_BASE_URL}{config.path}", headers, logger)
    data = response.json()
    if isinstance(data, dict):
        yield [data]
    elif isinstance(data, list) and data:
        yield data


def _get_service_list_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Fastly: resuming services from URL: {url}")
    else:
        url = _build_url(f"{FASTLY_BASE_URL}/service", {"per_page": SERVICE_PAGE_SIZE})

    while True:
        response = _fetch(session, url, headers, logger)
        items = response.json()
        if isinstance(items, list) and items:
            yield items

        next_url = _next_page_url(response)
        if not next_url:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(FastlyResumeConfig(next_url=next_url))
        url = next_url


def _iter_services_from_bookmark(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[str]:
    """Yield the service ids a fan-out endpoint still has to process, bookmarking each one once the
    caller has yielded its rows. If the bookmarked service no longer exists (deleted between runs),
    start over — merge dedupes the re-pulled rows."""
    services = list(_iter_services(session, headers, logger))
    service_ids = [s["id"] for s in services if isinstance(s, dict) and s.get("id")]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start = 0
    if resume is not None and resume.service_id and resume.service_id in service_ids:
        start = service_ids.index(resume.service_id)
        logger.debug(f"Fastly: resuming {config.name} from service_id={resume.service_id}")

    for service_id in service_ids[start:]:
        yield service_id
        # Bookmark the service AFTER yielding so a crash resumes here and re-yields. Advanced even for
        # a versionless (skipped) service so resume doesn't re-evaluate it every time.
        resumable_source_manager.save_state(FastlyResumeConfig(service_id=service_id))


def _get_version_scoped_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    service_id: str,
    path: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    version = _active_version_number(session, service_id, headers, logger)
    if version is None:
        logger.debug(f"Fastly: service {service_id} has no versions, skipping {config.name}")
        return []

    response = _fetch(
        session, f"{FASTLY_BASE_URL}{path.format(service_id=service_id, version=version)}", headers, logger
    )
    data = response.json()
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _get_fanout_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    for service_id in _iter_services_from_bookmark(session, config, headers, logger, resumable_source_manager):
        if config.kind == "version_list":
            response = _fetch(session, f"{FASTLY_BASE_URL}/service/{service_id}/version", headers, logger)
            data = response.json()
            rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        else:
            rows = _get_version_scoped_rows(session, config, service_id, config.path, headers, logger)

        rows = [_ensure_service_id(row, service_id) for row in rows]
        if rows:
            yield rows


def _get_version_resource_child_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    parent_path = config.parent_path
    parent_key = config.parent_key
    assert parent_path is not None and parent_key is not None

    for service_id in _iter_services_from_bookmark(session, config, headers, logger, resumable_source_manager):
        parents = _get_version_scoped_rows(session, config, service_id, parent_path, headers, logger)

        for parent in parents:
            if config.skip_parent_flag and parent.get(config.skip_parent_flag):
                continue

            parent_id = parent.get("id")
            if not parent_id:
                continue

            path = config.path.format(service_id=service_id, parent_id=parent_id)
            url = _build_url(f"{FASTLY_BASE_URL}{path}", {"per_page": CHILD_PAGE_SIZE})
            for response in _iter_linked_pages(session, url, headers, logger):
                items = response.json()
                if not isinstance(items, list):
                    continue
                rows = [
                    _ensure_id(_ensure_service_id(row, service_id), parent_key, parent_id)
                    for row in items
                    if isinstance(row, dict)
                ]
                if rows:
                    yield rows


def _iter_billing_pages(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[dict[str, Any]]:
    request = _request_fingerprint(path, params)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    cursor = None
    if resume is not None and resume.cursor and resume.cursor_request == request:
        cursor = resume.cursor
        logger.debug(f"Fastly: resuming {path} from cursor")

    while True:
        page_params = {**params, "cursor": cursor} if cursor else params
        response = _fetch(session, _build_url(f"{FASTLY_BASE_URL}{path}", page_params), headers, logger)
        payload = response.json()
        if not isinstance(payload, dict):
            return

        yield payload

        next_cursor = _next_cursor(payload)
        if not next_cursor:
            return
        # A cursor that repeats the one just sent would loop forever and re-yield the same page.
        if next_cursor == cursor:
            raise FastlyPaginationError(f"Fastly returned an unchanged cursor for {path}")
        cursor = next_cursor
        # Saved AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(FastlyResumeConfig(cursor=cursor, cursor_request=request))


def _get_billing_list_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    params = {"limit": INVOICE_PAGE_LIMIT}
    for payload in _iter_billing_pages(session, config.path, params, headers, logger, resumable_source_manager):
        data = payload.get("data")
        rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        if rows:
            yield rows


def _get_billing_usage_metrics_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    params = _usage_metrics_window()
    for payload in _iter_billing_pages(session, config.path, params, headers, logger, resumable_source_manager):
        rows = _flatten_usage_metrics(payload)
        if rows:
            yield rows


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FASTLY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # Redact the token so it never lands in captured HTTP samples — Fastly's custom `Fastly-Key`
    # header isn't covered by the transport's known-auth-header scrubbing.
    session = make_tracked_session(redact_values=(api_key,))

    if config.kind == "object":
        yield from _get_object_rows(session, config, headers, logger)
    elif config.kind == "service_list":
        yield from _get_service_list_rows(session, headers, logger, resumable_source_manager)
    elif config.kind == "version_resource_child":
        yield from _get_version_resource_child_rows(session, config, headers, logger, resumable_source_manager)
    elif config.kind == "billing_list":
        yield from _get_billing_list_rows(session, config, headers, logger, resumable_source_manager)
    elif config.kind == "billing_usage_metrics":
        yield from _get_billing_usage_metrics_rows(session, config, headers, logger, resumable_source_manager)
    else:
        yield from _get_fanout_rows(session, config, headers, logger, resumable_source_manager)


def fastly_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> SourceResponse:
    config = FASTLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


__all__ = ["FastlyResumeConfig", "fastly_source", "validate_credentials"]
