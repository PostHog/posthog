import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.settings import (
    PRODUCTBOARD_ENDPOINTS,
)

PRODUCTBOARD_BASE_URL = "https://api.productboard.com/v2"


class ProductboardRetryableError(Exception):
    pass


@dataclasses.dataclass
class ProductboardResumeConfig:
    next_url: str


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a `Z` suffix.

    Productboard's date/time filters expect ISO 8601 date-time strings; we normalise
    to UTC so naive watermarks from the DB compare correctly against tz-aware values.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL, percent-encoding values but keeping literal param keys.

    Productboard's entity filter uses the bracket key `type[]`, which we preserve
    verbatim while still encoding values (e.g. ISO timestamps containing `:`).
    """
    if not params:
        return base_url
    parts = [f"{key}={quote(str(value), safe='')}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(parts)}"


def _build_initial_params(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    config = PRODUCTBOARD_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}

    if config.entity_type:
        params["type[]"] = config.entity_type

    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        field = incremental_field or config.default_incremental_field
        filter_param = config.incremental_param_map.get(field) if field else None
        if filter_param:
            params[filter_param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(access_token: str, path: str) -> tuple[bool, int | None, str | None]:
    """Probe a single Productboard endpoint. Returns (ok, status_code, message)."""
    try:
        response = make_tracked_session().get(
            f"{PRODUCTBOARD_BASE_URL}{path}",
            headers=_get_headers(access_token),
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return False, None, str(e)

    if response.ok:
        return True, response.status_code, None

    try:
        message = response.json().get("message")
    except Exception:
        message = response.text or None

    return False, response.status_code, message


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ProductboardResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = PRODUCTBOARD_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    params = _build_initial_params(
        endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"Productboard: resuming from URL: {url}")
    else:
        url = _build_url(f"{PRODUCTBOARD_BASE_URL}{config.path}", params)

    @retry(
        retry=retry_if_exception_type((ProductboardRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict:
        response = make_tracked_session().get(page_url, headers=headers, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise ProductboardRetryableError(
                f"Productboard API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Productboard API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get("data", [])
        if not items:
            break

        next_url = data.get("links", {}).get("next")

        # Checkpoint the CURRENT page URL, not the next one: the batcher buffers across
        # page boundaries, so a yield can flush rows from several pages at once. On
        # resume we re-fetch this page and rely on primary-key merge to dedupe the rows
        # already yielded. Advancing the checkpoint to next_url here would strand any
        # current-page rows still buffered (not yet yielded) if we crashed mid-page.
        checkpoint_url = url

        for item in items:
            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()
                # Save state after yielding (not before) so a crash re-yields the last
                # batch rather than skipping it.
                resumable_source_manager.save_state(ProductboardResumeConfig(next_url=checkpoint_url))

        if not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def productboard_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ProductboardResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PRODUCTBOARD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
