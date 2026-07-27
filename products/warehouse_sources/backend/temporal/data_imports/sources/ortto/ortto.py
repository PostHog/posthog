import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.settings import (
    ORTTO_ENDPOINTS,
    ORTTO_REGION_HOSTS,
)

REQUEST_TIMEOUT_SECONDS = 60
# Plan-dependent rate limits (10-30 req/s) plus per-IP caps; back off on 429.
MAX_RETRY_ATTEMPTS = 5


class OrttoRetryableError(Exception):
    pass


@dataclasses.dataclass
class OrttoResumeConfig:
    # Pagination position within a single full-refresh sync. `cursor_id` pins
    # the result set for the people/accounts endpoints; offset-only endpoints
    # leave it None.
    next_offset: int
    cursor_id: Optional[str] = None


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"X-Api-Key": api_key}, redact_values=(api_key,))


def _base_url(region: str) -> str:
    return ORTTO_REGION_HOSTS.get(region, ORTTO_REGION_HOSTS["global"])


def _flatten_custom_field(entry: dict[str, Any]) -> dict[str, Any]:
    # Person custom fields arrive wrapped ({"field": {...}, "tracked_value": ...});
    # account custom fields arrive flat.
    if isinstance(entry.get("field"), dict):
        return {**entry["field"], "tracked_value": entry.get("tracked_value")}
    return entry


def validate_credentials(region: str, api_key: str) -> bool:
    """Confirm the API key works with a cheap custom-field listing probe."""
    try:
        response = _get_session(api_key).post(
            f"{_base_url(region)}/v1/person/custom-field/get",
            json={},
            timeout=15,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OrttoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ORTTO_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    base_url = _base_url(region)

    @retry(
        retry=retry_if_exception_type((OrttoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(path: str, body: dict[str, Any]) -> Any:
        response = session.post(f"{base_url}{path}", json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OrttoRetryableError(f"Ortto API error (retryable): status={response.status_code}, path={path}")

        if not response.ok:
            logger.error(f"Ortto API error: status={response.status_code}, body={response.text[:500]}, path={path}")
            response.raise_for_status()

        return response.json()

    def extract_items(data: Any) -> list[dict[str, Any]]:
        if config.data_key is not None:
            items = data.get(config.data_key) if isinstance(data, dict) else None
        else:
            items = data
        return items if isinstance(items, list) else []

    if config.pagination == "none":
        data = fetch(config.path, {})
        items = extract_items(data)
        if config.data_key == "fields":
            items = [_flatten_custom_field(item) for item in items]
        if items:
            yield items
        return

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.next_offset if resume_config is not None else 0
    cursor_id = resume_config.cursor_id if resume_config is not None else None
    if resume_config is not None:
        logger.debug(f"Ortto: resuming {endpoint} from offset {offset}")

    # Every retrieval endpoint is a POST with pagination in the JSON body.
    fields: Optional[list[str]] = None
    if config.builtin_fields is not None:
        fields = list(config.builtin_fields)
        if config.custom_fields_path is not None:
            custom_fields_body = fetch(config.custom_fields_path, {})
            custom_entries = custom_fields_body.get("fields") if isinstance(custom_fields_body, dict) else None
            for entry in custom_entries or []:
                field_id = _flatten_custom_field(entry).get("id")
                if field_id:
                    fields.append(field_id)

    while True:
        body: dict[str, Any] = {"limit": config.page_size, "offset": offset}
        if fields is not None:
            body["fields"] = fields
        if cursor_id is not None:
            body["cursor_id"] = cursor_id

        data = fetch(config.path, body)
        items = extract_items(data)

        if items:
            yield items

        if config.pagination == "cursor":
            if not isinstance(data, dict) or not data.get("has_more"):
                break
            offset = data.get("next_offset", offset + len(items))
            cursor_id = data.get("cursor_id") or cursor_id
        else:
            if len(items) < config.page_size:
                break
            offset += len(items)

        # Save state AFTER yielding so a crash re-yields the in-flight page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(OrttoResumeConfig(next_offset=offset, cursor_id=cursor_id))


def ortto_source(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OrttoResumeConfig],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
    )
