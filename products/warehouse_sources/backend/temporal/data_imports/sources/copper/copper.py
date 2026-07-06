import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import (
    COPPER_DEFAULT_PAGE_SIZE,
    COPPER_ENDPOINTS,
    CopperEndpointConfig,
)

COPPER_BASE_URL = "https://api.copper.com/developer_api/v1"
# Copper requires this header on every request; "developer" is the documented value for API-key auth.
COPPER_APPLICATION = "developer"

# Maps an advertised incremental field to its server-side filter param and sort column.
# Copper's search endpoints filter by `minimum_modified_date` / `minimum_created_date`
# (inclusive Unix-epoch-seconds bounds) and sort by `date_modified` / `date_created`.
INCREMENTAL_FIELD_TO_PARAMS: dict[str, tuple[str, str]] = {
    "date_modified": ("minimum_modified_date", "date_modified"),
    "date_created": ("minimum_created_date", "date_created"),
}


class CopperRetryableError(Exception):
    pass


@dataclasses.dataclass
class CopperResumeConfig:
    page_number: int


def _get_headers(api_key: str, user_email: str) -> dict[str, str]:
    return {
        "X-PW-AccessToken": api_key,
        "X-PW-Application": COPPER_APPLICATION,
        "X-PW-UserEmail": user_email,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> int | None:
    """Coerce the stored incremental watermark into the Unix-epoch-seconds Copper expects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        # Treat naive datetimes as UTC so the epoch cutoff doesn't shift with the host timezone.
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_credentials(api_key: str, user_email: str) -> tuple[bool, str | None]:
    session = make_tracked_session(headers=_get_headers(api_key, user_email), redact_values=(api_key,))
    try:
        response = session.get(f"{COPPER_BASE_URL}/account", timeout=10)
        if response.status_code == 200:
            return True, None
        if response.status_code in (401, 403):
            return False, "Invalid Copper credentials. Check your API key and the email it belongs to."
        return False, f"Copper credential check failed with status {response.status_code}"
    except Exception as e:
        return False, str(e)
    finally:
        session.close()


def _build_search_body(
    config: CopperEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    page_size: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {"page_size": page_size}

    if should_use_incremental_field and incremental_field in INCREMENTAL_FIELD_TO_PARAMS:
        min_param, sort_field = INCREMENTAL_FIELD_TO_PARAMS[incremental_field]
        body["sort_by"] = sort_field
        body["sort_direction"] = "asc"
        last_value = _to_unix_seconds(db_incremental_field_last_value)
        if last_value is not None:
            # Inclusive bound: the boundary row is re-fetched and deduped by merge on primary key.
            body[min_param] = last_value
    elif config.full_refresh_sort:
        body["sort_by"] = config.full_refresh_sort
        body["sort_direction"] = "asc"

    return body


def get_rows(
    api_key: str,
    user_email: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = COPPER_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_get_headers(api_key, user_email), redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((CopperRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(method: str, url: str, body: dict[str, Any] | None) -> Any:
        response = session.request(method, url, json=body, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise CopperRetryableError(f"Copper API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Copper API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    url = f"{COPPER_BASE_URL}{config.path}"

    try:
        if not config.paginated:
            data = fetch(config.method, url, None)
            if isinstance(data, list) and data:
                yield data
            return

        page_size = COPPER_DEFAULT_PAGE_SIZE
        body = _build_search_body(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field, page_size
        )

        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        page_number = resume_config.page_number if resume_config is not None else 1
        if resume_config is not None:
            logger.debug(f"Copper: resuming {endpoint} from page {page_number}")

        while True:
            body["page_number"] = page_number
            data = fetch(config.method, url, body)

            if not isinstance(data, list) or not data:
                break

            yield data

            if len(data) < page_size:
                break

            page_number += 1
            resumable_source_manager.save_state(CopperResumeConfig(page_number=page_number))
    finally:
        session.close()


def copper_source(
    api_key: str,
    user_email: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = COPPER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            user_email=user_email,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        partition_keys=config.partition_keys,
        sort_mode="asc",
    )
