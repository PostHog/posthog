import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.settings import (
    BREVO_ENDPOINTS,
    BrevoEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BREVO_BASE_URL = "https://api.brevo.com/v3"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class BrevoRetryableError(Exception):
    pass


@dataclasses.dataclass
class BrevoResumeConfig:
    # Offset (record index) of the next page to fetch within the current sync.
    offset: int


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "api-key": api_key,
        "accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a value as Brevo's expected UTC date-time (YYYY-MM-DDTHH:mm:ss.SSSZ).

    Brevo rejects the +00:00 offset produced by isoformat(), so we emit the Z suffix.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_datetime(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def validate_credentials(api_key: str) -> bool:
    """Cheap probe to confirm the API key is genuine."""
    try:
        session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
        response = session.get(f"{BREVO_BASE_URL}/account", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _build_base_params(
    config: BrevoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    # Brevo only sorts by record creation date. Sorting ascending keeps pagination boundaries
    # stable as new rows are inserted mid-sync and makes createdAt-based incremental monotonic.
    if config.paginate:
        params["sort"] = "asc"

    if should_use_incremental_field and incremental_field and db_incremental_field_last_value:
        param_name = config.incremental_param_map.get(incremental_field)
        if param_name:
            params[param_name] = _format_datetime(db_incremental_field_last_value)

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrevoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BREVO_ENDPOINTS[endpoint]
    base_params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config else 0
    if resume_config is not None:
        logger.debug(f"Brevo: resuming {endpoint} from offset {offset}")

    # One session reused across all pages (TCP/connection reuse). `tenacity` below is the sole
    # retry mechanism, so disable the transport's built-in urllib3 retries to avoid nested backoff.
    # `redact_values` masks the api-key header value in logs and sample capture.
    session = make_tracked_session(headers=_get_headers(api_key), retry=Retry(total=0), redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((BrevoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        url = f"{BREVO_BASE_URL}{config.path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise BrevoRetryableError(f"Brevo API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Brevo API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    try:
        while True:
            params = dict(base_params)
            if config.paginate:
                params["limit"] = config.page_size
                params["offset"] = offset

            data = fetch_page(params)
            # Brevo omits the array key entirely (or sets it to null) for an empty collection,
            # e.g. {"count": 0} with no "campaigns"/"segments" key. Treat that as an empty page
            # rather than crashing the sync.
            items = data.get(config.data_key) or []

            if items:
                yield items

            if not config.paginate or len(items) < config.page_size:
                break

            offset += config.page_size
            # Save AFTER yielding so a crash re-yields the last page (merge dedupes on primary key)
            # rather than skipping it.
            resumable_source_manager.save_state(BrevoResumeConfig(offset=offset))
    finally:
        session.close()


def brevo_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrevoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = BREVO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
