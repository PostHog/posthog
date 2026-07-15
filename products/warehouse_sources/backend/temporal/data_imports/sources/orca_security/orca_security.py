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
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import (
    DEFAULT_REGION,
    ORCA_ENDPOINTS,
    ORCA_REGION_HOSTS,
    PAGE_SIZE,
    QUERY_PATH,
    OrcaEndpointConfig,
)

REQUEST_TIMEOUT = 120


class OrcaRetryableError(Exception):
    pass


@dataclasses.dataclass
class OrcaResumeConfig:
    # Serving Layer offset (`start_at_index`) of the next page to fetch. Offset pagination has no
    # opaque cursor, so the offset alone is enough to pick back up after a heartbeat timeout.
    start_at_index: int = 0


def _host(region: str) -> str:
    return ORCA_REGION_HOSTS.get(region or DEFAULT_REGION, ORCA_REGION_HOSTS[DEFAULT_REGION])


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an ISO 8601 string. Orca's Serving Layer is strict about the format."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_payload(
    config: OrcaEndpointConfig,
    start_at_index: int,
    incremental_field: str | None,
    formatted_last_value: str | None,
) -> dict[str, Any]:
    """Build the Serving Layer object_set query body for one page of a stream."""
    query: dict[str, Any] = {"models": [config.model], "type": "object_set"}

    # Server-side incremental filter, only for streams with a verified `date_gte`-able field.
    if config.incremental_key and formatted_last_value:
        filter_field = incremental_field or config.incremental_key
        query["with"] = {
            "type": "operation",
            "operator": "and",
            "values": [
                {
                    "key": filter_field,
                    "values": [formatted_last_value],
                    "type": "datetime",
                    "operator": "date_gte",
                    "value_type": "days",
                }
            ],
        }

    payload: dict[str, Any] = {
        "query": query,
        "limit": PAGE_SIZE,
        "start_at_index": start_at_index,
    }
    # Ascending order on the incremental field keeps the pipeline's watermark advancing correctly
    # (matches SourceResponse.sort_mode="asc") and gives offset pagination a stable order.
    if config.incremental_key:
        payload["order_by[]"] = [config.incremental_key]

    return payload


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Serving Layer object into a flat row.

    Objects arrive as ``{"id", "type", "data": {"Field": {"value": ...}}}``. We lift the stable
    top-level ``id``/``type`` and unwrap each ``{"value": ...}`` field to the row root so the
    warehouse table has queryable columns instead of a single nested blob.
    """
    row: dict[str, Any] = {}
    if "id" in item:
        row["id"] = item["id"]
    if "type" in item:
        row["type"] = item["type"]

    data = item.get("data")
    if isinstance(data, dict):
        for key, wrapped in data.items():
            if isinstance(wrapped, dict) and "value" in wrapped:
                row[key] = wrapped["value"]
            else:
                row[key] = wrapped
    return row


@retry(
    retry=retry_if_exception_type(
        (
            OrcaRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], payload: dict[str, Any], logger: FilteringBoundLogger
) -> dict:
    response = session.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise OrcaRetryableError(f"Orca API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Orca API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str, region: str) -> tuple[bool, Optional[str]]:
    """Probe the token against a cheap single-row Serving Layer query."""
    url = f"{_host(region)}{QUERY_PATH}"
    payload = {"query": {"models": ["CloudAccount"], "type": "object_set"}, "limit": 1, "start_at_index": 0}
    try:
        response = make_tracked_session().post(url, headers=_headers(api_token), json=payload, timeout=30)
    except Exception as e:
        return False, f"Could not reach Orca Security ({e}). Check your network and the selected region, then retry."

    if response.status_code in (401, 403):
        return (
            False,
            "Orca rejected the API token. Generate a new token in Settings → Users & Permissions → API and reconnect.",
        )
    if not response.ok:
        return False, f"Orca API returned an unexpected status ({response.status_code}). Please retry."
    return True, None


def get_rows(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OrcaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ORCA_ENDPOINTS[endpoint]
    url = f"{_host(region)}{QUERY_PATH}"
    headers = _headers(api_token)
    session = make_tracked_session()

    formatted_last_value = (
        _format_datetime(db_incremental_field_last_value)
        if should_use_incremental_field and config.incremental_key and db_incremental_field_last_value
        else None
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_at_index = resume.start_at_index if resume else 0
    if resume:
        logger.debug(f"Orca: resuming {endpoint} from start_at_index={start_at_index}")

    while True:
        payload = _build_payload(config, start_at_index, incremental_field, formatted_last_value)
        data = _fetch_page(session, url, headers, payload, logger)

        items = data.get("data", [])
        if not items:
            break

        yield [_normalize_item(item) for item in items]

        # `next_page_token` is the next offset; fall back to advancing by page size. A short page
        # (fewer than PAGE_SIZE rows) means we've reached the end.
        next_token = data.get("next_page_token")
        if not next_token and len(items) < PAGE_SIZE:
            break
        start_at_index = int(next_token) if next_token else start_at_index + len(items)

        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        resumable_source_manager.save_state(OrcaResumeConfig(start_at_index=start_at_index))


def orca_source(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OrcaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ORCA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
