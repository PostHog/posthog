import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    PINGDOM_ENDPOINTS,
    PingdomEndpointConfig,
)

PINGDOM_BASE_URL = "https://api.pingdom.com/api/3.1"
REQUEST_TIMEOUT_SECONDS = 60
# Pingdom enforces two-tier rate limits (Req-Limit-Short / Req-Limit-Long
# headers) and returns 429 on exceed; exponential backoff is sufficient.
MAX_RETRY_ATTEMPTS = 5


class PingdomRetryableError(Exception):
    pass


@dataclasses.dataclass
class PingdomResumeConfig:
    # Pingdom paginates with limit/offset; the static query params (limit,
    # incremental `from` filter) are deterministically rebuilt from the endpoint
    # config and job inputs on resume.
    offset: int


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch seconds for Pingdom's `from` filter."""
    if value is None or isinstance(value, bool):
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


def _extract_items(data: dict[str, Any], data_key: str) -> list[dict[str, Any]]:
    node: Any = data
    for key in data_key.split("."):
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    return node if isinstance(node, list) else []


def _build_params(config: PingdomEndpointConfig, from_value: Optional[int], offset: int) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size, "offset": offset}
    if from_value is not None:
        params["from"] = from_value
    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{PINGDOM_BASE_URL}{path}"
    return f"{PINGDOM_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with a cheap one-check listing probe."""
    try:
        response = _get_session(api_token).get(
            _build_url("/checks", {"limit": 1}),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PingdomResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PINGDOM_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    from_value = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Pingdom: resuming {endpoint} from offset {offset}")

    @retry(
        retry=retry_if_exception_type((PingdomRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise PingdomRetryableError(f"Pingdom API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Pingdom API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        url = _build_url(config.path, _build_params(config, from_value, offset))
        data = fetch_page(url)
        items = _extract_items(data, config.data_key)

        if items:
            yield items

        if len(items) < config.page_size:
            break

        offset += config.page_size
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(PingdomResumeConfig(offset=offset))


def pingdom_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PingdomResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PINGDOM_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        has_duplicate_primary_keys=config.has_duplicate_primary_keys or None,
    )
