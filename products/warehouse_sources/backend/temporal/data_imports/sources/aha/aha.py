import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import (
    AHA_ENDPOINTS,
    PER_PAGE,
    AhaEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AHA_API_PATH = "/api/v1"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<subdomain>.aha.io`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class AhaRetryableError(Exception):
    pass


@dataclasses.dataclass
class AhaResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: int | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce user input to a bare, validated Aha! subdomain label.

    Accepts either the full host (``yourcompany.aha.io``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<subdomain>.aha.io``.
    """
    cleaned = subdomain.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".aha.io")
    if not _SUBDOMAIN_RE.match(cleaned):
        raise ValueError(
            f"Invalid Aha! account domain: {subdomain!r}. Enter just your subdomain, e.g. 'yourcompany' "
            "for yourcompany.aha.io."
        )
    return cleaned


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.aha.io{AHA_API_PATH}"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_updated_since(value: Any) -> str:
    """Format an incremental cursor as the ISO8601 UTC string Aha! expects for `updated_since`."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def _build_initial_params(
    config: AhaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}
    # Only Aha!'s `updated_since`-capable endpoints filter server-side; everything else is full refresh.
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["updated_since"] = _format_updated_since(db_incremental_field_last_value)
    return params


@retry(
    retry=retry_if_exception_type((AhaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # Aha! enforces 300 req/min and 20 req/sec; 429 carries reset headers. Back off and retry rather
    # than failing the sync. Transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise AhaRetryableError(f"Aha! API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Aha! API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _has_more_pages(pagination: dict[str, Any], page: int, item_count: int) -> bool:
    """Decide whether to fetch another page.

    Prefer Aha!'s `pagination.total_pages`; fall back to a full-page heuristic if the metadata is
    ever absent (a full page implies there may be more).
    """
    total_pages = pagination.get("total_pages")
    if isinstance(total_pages, int):
        return page < total_pages
    return item_count >= PER_PAGE


def get_rows(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = AHA_ENDPOINTS[endpoint]
    base_url = _base_url(subdomain)
    headers = _headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None and resume.next_page else 1
    if page > 1:
        logger.debug(f"Aha!: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, _build_url(base_url, config.path, {**params, "page": page}), headers, logger)
        items = data.get(config.response_key, [])
        if not items:
            break

        has_more = _has_more_pages(data.get("pagination", {}), page, len(items))

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
                # merge dedupes on the primary key.
                if has_more:
                    resumable_source_manager.save_state(AhaResumeConfig(next_page=page + 1))

        if not has_more:
            break
        page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def aha_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = AHA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, int | None]:
    """Probe Aha!'s `/me` endpoint to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the subdomain is malformed so the caller can surface a precise message.
    """
    url = _build_url(_base_url(subdomain), "/me", {})
    try:
        response = make_tracked_session().get(url, headers=_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
