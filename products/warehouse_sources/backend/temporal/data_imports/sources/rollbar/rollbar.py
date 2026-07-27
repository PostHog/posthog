import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.settings import ROLLBAR_ENDPOINTS

ROLLBAR_BASE_URL = "https://api.rollbar.com/api/1"
# Instances support a keyset `limit` of up to 5000; keep it moderate so pages
# stay well under the pipeline's buffering thresholds.
KEYSET_PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60
# Rate limits are per-token and user-configurable; 429 on breach.
MAX_RETRY_ATTEMPTS = 5


class RollbarRetryableError(Exception):
    pass


@dataclasses.dataclass
class RollbarResumeConfig:
    # Page-paginated endpoints persist the 1-indexed page; the occurrences
    # keyset walk persists the last (lowest) occurrence id seen instead.
    page: Optional[int] = None
    last_id: Optional[int] = None


def _get_session(access_token: str) -> requests.Session:
    return make_tracked_session(headers={"X-Rollbar-Access-Token": access_token}, redact_values=(access_token,))


def _to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_items(body: Any, data_key: Optional[str]) -> list[dict[str, Any]]:
    result = body.get("result") if isinstance(body, dict) else None
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and data_key is not None:
        items = result.get(data_key)
        return items if isinstance(items, list) else []
    return []


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{ROLLBAR_BASE_URL}{path}"
    return f"{ROLLBAR_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(access_token: str) -> bool:
    """Confirm the project access token is valid with a cheap environments probe."""
    try:
        response = _get_session(access_token).get(
            _build_url("/environments", {}),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RollbarResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ROLLBAR_ENDPOINTS[endpoint]
    session = _get_session(access_token)

    @retry(
        retry=retry_if_exception_type((RollbarRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch(url: str) -> Any:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise RollbarRetryableError(f"Rollbar API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Rollbar API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "keyset":
        # Occurrences are strictly descending by id. Walk from the head (or the
        # resumed keyset position) and stop once rows cross the persisted
        # incremental watermark.
        watermark = _to_int(db_incremental_field_last_value) if should_use_incremental_field else None
        last_id: Optional[int] = resume_config.last_id if resume_config is not None else None
        if last_id is not None:
            logger.debug(f"Rollbar: resuming {endpoint} from lastId {last_id}")

        while True:
            params: dict[str, Any] = {"limit": KEYSET_PAGE_SIZE}
            if last_id is not None:
                params["lastId"] = last_id
            body = fetch(_build_url(config.path, params))
            items = _extract_items(body, config.data_key)

            if watermark is not None:
                items = [item for item in items if (_to_int(item["id"]) or 0) > watermark]

            if items:
                yield items

            if len(items) < KEYSET_PAGE_SIZE:
                # Short page: either the stream is exhausted or we crossed the
                # watermark (filtered rows out).
                break

            last_id = min((_to_int(item["id"]) or 0) for item in items)
            # Save state AFTER yielding the page so a crash re-yields the last
            # page (merge dedupes on primary key) rather than skipping it.
            resumable_source_manager.save_state(RollbarResumeConfig(last_id=last_id))
        return

    page = resume_config.page if resume_config is not None and resume_config.page is not None else 1
    if resume_config is not None:
        logger.debug(f"Rollbar: resuming {endpoint} from page {page}")

    while True:
        body = fetch(_build_url(config.path, {"page": page}))
        items = _extract_items(body, config.data_key)

        if not items:
            break

        yield items

        page += 1
        resumable_source_manager.save_state(RollbarResumeConfig(page=page))


def rollbar_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RollbarResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ROLLBAR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Occurrences arrive newest-first; the pipeline only commits the
        # incremental watermark for desc sources once the run completes.
        sort_mode="desc" if config.pagination == "keyset" else "asc",
    )
