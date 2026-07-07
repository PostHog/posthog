import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import (
    FASTLY_ENDPOINTS,
    FastlyEndpointConfig,
)

FASTLY_BASE_URL = "https://api.fastly.com"

# Fastly caps read requests at ~6,000/minute per token. `/service` supports page-number pagination;
# the account's service count is small in practice, so a large page keeps the round-trip count down.
SERVICE_PAGE_SIZE = 100


class FastlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class FastlyResumeConfig:
    # Next page URL for the paginated top-level `services` list.
    next_url: str | None = None
    # Bookmark for fan-out endpoints: the service we were processing when state was saved. On resume
    # we restart at this service and re-yield its rows (merge dedupes on the primary key).
    service_id: str | None = None


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


def _ensure_service_id(row: dict[str, Any], service_id: str) -> dict[str, Any]:
    """Fastly's version-scoped objects already carry `service_id`, but inject it defensively so the
    composite primary key is never missing its parent identifier."""
    if not row.get("service_id"):
        row = {**row, "service_id": service_id}
    return row


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


def _get_fanout_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    services = list(_iter_services(session, headers, logger))
    service_ids = [s["id"] for s in services if isinstance(s, dict) and s.get("id")]

    # Resolve the saved service bookmark to the slice still to process. If the bookmarked service no
    # longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start = 0
    if resume is not None and resume.service_id and resume.service_id in service_ids:
        start = service_ids.index(resume.service_id)
        logger.debug(f"Fastly: resuming {config.name} from service_id={resume.service_id}")

    for service_id in service_ids[start:]:
        rows: list[dict[str, Any]] = []
        if config.kind == "version_list":
            response = _fetch(session, f"{FASTLY_BASE_URL}/service/{service_id}/version", headers, logger)
            data = response.json()
            rows = data if isinstance(data, list) else []
        else:
            version = _active_version_number(session, service_id, headers, logger)
            if version is None:
                logger.debug(f"Fastly: service {service_id} has no versions, skipping {config.name}")
            else:
                path = config.path.format(service_id=service_id, version=version)
                response = _fetch(session, f"{FASTLY_BASE_URL}{path}", headers, logger)
                data = response.json()
                rows = data if isinstance(data, list) else []

        rows = [_ensure_service_id(row, service_id) for row in rows if isinstance(row, dict)]
        if rows:
            yield rows
        # Bookmark the service AFTER yielding so a crash resumes here and re-yields. Advanced even for
        # a versionless (skipped) service so resume doesn't re-evaluate it every time.
        resumable_source_manager.save_state(FastlyResumeConfig(service_id=service_id))


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
