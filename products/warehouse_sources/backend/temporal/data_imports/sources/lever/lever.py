import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests  # used for exception types in the tenacity retry predicate
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.settings import (
    LEVER_ENDPOINTS,
    LeverEndpointConfig,
)

LEVER_BASE_URL = "https://api.lever.co/v1"
REQUEST_TIMEOUT_SECONDS = 60

# Lever returns these top-level fields as Unix-epoch milliseconds. We store them as epoch
# seconds (int) so datetime partitioning and incremental watermarks behave like the other
# epoch-based sources (Clerk, Stripe).
_TIMESTAMP_FIELDS = ("createdAt", "updatedAt")


class LeverRetryableError(Exception):
    pass


@dataclasses.dataclass
class LeverResumeConfig:
    # Lever paginates with an opaque `offset` token returned as `next` in each response.
    offset: str


def _auth(api_key: str) -> tuple[str, str]:
    # Lever uses HTTP Basic auth with the API key as the username and a blank password.
    return (api_key, "")


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    for ts_field in _TIMESTAMP_FIELDS:
        value = item.get(ts_field)
        if isinstance(value, int):
            # Integer division keeps the int64 type that delta tables expect.
            item[ts_field] = value // 1000
    return item


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    url = f"{LEVER_BASE_URL}/postings"
    session = make_tracked_session()
    try:
        response = session.get(url, auth=_auth(api_key), params={"limit": 1}, timeout=10)
    except Exception as e:
        return False, str(e)
    finally:
        session.close()

    if response.status_code == 200:
        return True, None

    if response.status_code in (401, 403):
        return False, "Invalid Lever API key. Please check your key and try again."

    return False, f"Lever API returned an unexpected status code: {response.status_code}"


def _build_initial_params(
    config: LeverEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}

    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_filter_params.get(incremental_field)
        if filter_param:
            # The stored watermark is epoch seconds; Lever's timestamp filters expect
            # milliseconds. `_start` filters are inclusive — merge dedupes the boundary rows.
            params[filter_param] = int(db_incremental_field_last_value) * 1000

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LeverResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = LEVER_ENDPOINTS[endpoint]
    url = f"{LEVER_BASE_URL}{config.path}"
    session = make_tracked_session()

    base_params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset: str | None = resume_config.offset if resume_config else None
    if offset:
        logger.debug(f"Lever: resuming {endpoint} from offset token")

    @retry(
        retry=retry_if_exception_type((LeverRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        response = session.get(url, auth=_auth(api_key), params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise LeverRetryableError(f"Lever API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Lever API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    try:
        while True:
            params = dict(base_params)
            if offset:
                params["offset"] = offset

            data = fetch_page(params)

            items = data.get("data", [])
            if items:
                yield [_normalize_item(item) for item in items]

            if not data.get("hasNext"):
                break

            next_offset = data.get("next")
            if not next_offset:
                # Lever signalled more pages (`hasNext`) but gave us no cursor to fetch
                # them. Breaking here would silently truncate the sync, so fail loudly and
                # let the pipeline retry instead of completing with partial data.
                raise Exception(f"Lever: hasNext was true but no next offset token returned for endpoint={endpoint}")

            # Save state after yielding so a crash re-yields the last batch (merge dedupes
            # on the primary key) rather than skipping it.
            offset = next_offset
            resumable_source_manager.save_state(LeverResumeConfig(offset=offset))
    finally:
        session.close()


def lever_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LeverResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = LEVER_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
