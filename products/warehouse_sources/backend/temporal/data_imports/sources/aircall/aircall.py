import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.settings import (
    AIRCALL_ENDPOINTS,
    AircallEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AIRCALL_BASE_URL = "https://api.aircall.io/v1"
# Aircall caps list pages at 50 items.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class AircallRetryableError(Exception):
    pass


@dataclasses.dataclass
class AircallResumeConfig:
    next_url: str


def _basic_auth_token(api_id: str, api_token: str) -> str:
    return base64.b64encode(f"{api_id}:{api_token}".encode("ascii")).decode("ascii")


def _get_headers(api_id: str, api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Basic {_basic_auth_token(api_id, api_token)}",
        "Accept": "application/json",
    }


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for Aircall's `from` filter.

    Aircall stores and filters timestamps as epoch seconds, so the persisted watermark is
    already an int in the common case; datetimes are accepted defensively.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{AIRCALL_BASE_URL}{path}"
    return f"{AIRCALL_BASE_URL}{path}?{urlencode(clean_params)}"


def _build_params(config: AircallEndpointConfig, from_value: Optional[int]) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    # Ascending creation order keeps already-fetched pages stable and lets the incremental
    # watermark advance monotonically. `from` filters on the resource creation date.
    if config.incremental_fields or config.reanchor_field:
        params["order"] = "asc"
    if from_value is not None:
        params["from"] = from_value
    return params


def validate_credentials(api_id: str, api_token: str) -> bool:
    """Confirm the API key pair is valid. /v1/ping is a cheap authenticated probe."""
    try:
        response = make_tracked_session().get(
            f"{AIRCALL_BASE_URL}/ping",
            headers=_get_headers(api_id, api_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_id: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AircallResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AIRCALL_ENDPOINTS[endpoint]
    headers = _get_headers(api_id, api_token)

    cursor_field = incremental_field or config.reanchor_field
    from_value = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Aircall: resuming from URL: {url}")
    else:
        url = _build_url(config.path, _build_params(config, from_value))

    @retry(
        retry=retry_if_exception_type((AircallRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Aircall rate-limits at 120 req/min; 429s carry a reset header but exponential
        # backoff is sufficient here.
        if response.status_code == 429 or response.status_code >= 500:
            raise AircallRetryableError(f"Aircall API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Aircall API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    # Latest value of the re-anchor field seen across the whole run. Used to step `from`
    # past Aircall's hard 10k-record-per-query cap on calls/contacts once a page chain ends.
    max_cursor: Optional[int] = None

    while True:
        data = fetch_page(url)
        items = data.get(config.data_key, []) or []

        if items:
            yield items

            if cursor_field is not None:
                page_max = max(
                    (cursor for cursor in (_to_epoch(item.get(cursor_field)) for item in items) if cursor is not None),
                    default=None,
                )
                if page_max is not None and (max_cursor is None or page_max > max_cursor):
                    max_cursor = page_max

        next_url = (data.get("meta") or {}).get("next_page_link")

        if next_url:
            resumable_source_manager.save_state(AircallResumeConfig(next_url=next_url))
            url = next_url
            continue

        # Page chain ended. For capped endpoints, re-anchor on the latest cursor value to
        # fetch records beyond the 10k window. The strict-advance guard prevents an infinite
        # loop when many records share the boundary timestamp.
        if (
            config.reanchor_field is not None
            and max_cursor is not None
            and (from_value is None or max_cursor > from_value)
        ):
            from_value = max_cursor
            url = _build_url(config.path, _build_params(config, from_value))
            resumable_source_manager.save_state(AircallResumeConfig(next_url=url))
            logger.debug(f"Aircall: re-anchoring {endpoint} from={from_value} to page around the 10k cap")
            continue

        break


def aircall_source(
    api_id: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AircallResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = AIRCALL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_id=api_id,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
