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
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import (
    CRUNCHBASE_ENDPOINTS,
    CrunchbaseEndpointConfig,
)

CRUNCHBASE_BASE_URL = "https://api.crunchbase.com/v4/data"
# Search pages cap at 1000 entities.
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 120
# 200 calls/min rate limit; backoff on 429.
MAX_RETRY_ATTEMPTS = 5


class CrunchbaseRetryableError(Exception):
    pass


@dataclasses.dataclass
class CrunchbaseResumeConfig:
    # Keyset pagination: `after_id` is the uuid of the last entity of the
    # previous page; static body parts are rebuilt from job inputs on resume.
    after_id: str


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"X-cb-user-key": api_key}, redact_values=(api_key,))


def _format_updated_at(value: Any) -> str:
    """Format an incremental cursor for an updated_at gte predicate (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _build_body(
    config: CrunchbaseEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    after_id: Optional[str],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "field_ids": config.field_ids,
        "limit": PAGE_SIZE,
        # Ascending updated_at order keeps the incremental watermark monotonic
        # and gives stable pages on full scans too.
        "order": [{"field_id": "updated_at", "sort": "asc"}],
    }

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        body["query"] = [
            {
                "type": "predicate",
                "field_id": "updated_at",
                "operator_id": "gte",
                "values": [_format_updated_at(db_incremental_field_last_value)],
            }
        ]

    if after_id is not None:
        body["after_id"] = after_id

    return body


def _flatten_entity(entity: dict[str, Any]) -> dict[str, Any]:
    # Search hits nest the requested fields under `properties`; hoist them so
    # the table gets real columns and the uuid is available as the primary key.
    properties = entity.get("properties") or {}
    return {**properties, "uuid": entity["uuid"]}


def validate_credentials(api_key: str) -> bool:
    """Confirm the user key is valid AND licensed — the Search API requires a
    paid Enterprise/Applications license, so only a 200 means syncs can work."""
    try:
        session = _get_session(api_key)
        response = session.post(
            f"{CRUNCHBASE_BASE_URL}/searches/organizations",
            json={"field_ids": ["identifier"], "limit": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CrunchbaseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CRUNCHBASE_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    url = f"{CRUNCHBASE_BASE_URL}/searches/{config.collection}"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after_id: Optional[str] = resume_config.after_id if resume_config is not None else None
    if after_id is not None:
        logger.debug(f"Crunchbase: resuming {endpoint} from after_id {after_id}")

    @retry(
        retry=retry_if_exception_type((CrunchbaseRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch_page(body: dict[str, Any]) -> dict[str, Any]:
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise CrunchbaseRetryableError(
                f"Crunchbase API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Crunchbase API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        body = _build_body(config, should_use_incremental_field, db_incremental_field_last_value, after_id)
        data = fetch_page(body)
        entities = data.get("entities", []) or []
        items = [_flatten_entity(entity) for entity in entities]

        if items:
            yield items

        if len(entities) < PAGE_SIZE:
            break

        # `_flatten_entity` already asserted every entity has a uuid, so the
        # last one is a safe keyset cursor for the next page.
        after_id = entities[-1]["uuid"]
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(CrunchbaseResumeConfig(after_id=after_id))


def crunchbase_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CrunchbaseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CRUNCHBASE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )
