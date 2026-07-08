import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import (
    PAGE_SIZE,
    SHOPWIRED_ENDPOINTS,
)

# ShopWired's dedicated API domain; the version segment is mandatory in every path.
SHOPWIRED_BASE_URL = "https://api.ecommerceapi.uk/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe used to confirm an API key/secret pair is genuine. Keys are account-wide, so one
# probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/products/count"


class ShopWiredRetryableError(Exception):
    pass


@dataclasses.dataclass
class ShopWiredResumeConfig:
    # Number of rows already yielded — ShopWired paginates with `count`/`offset` query params, so a
    # crashed sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0
    # The `from` created-date filter (UNIX timestamp) the interrupted run was using. Pinned in the
    # resume state so a resumed run keeps the same window — recomputing it from a watermark that
    # advanced mid-run would shift rows under the saved offset.
    from_timestamp: int | None = None


def _make_session(api_key: str, api_secret: str) -> requests.Session:
    # Private-app auth is HTTP Basic with the API key as username and the secret as password.
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key, api_secret))
    session.auth = (api_key, api_secret)
    return session


def to_unix_timestamp(value: Any) -> int | None:
    """Convert an incremental watermark (datetime, date, epoch number, or date string) to a UNIX
    timestamp for ShopWired's `from` query param."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day).timestamp())
    if isinstance(value, str) and value.strip():
        try:
            return int(parser.parse(value).timestamp())
        except (ValueError, OverflowError):
            return None
    return None


@retry(
    retry=retry_if_exception_type((ShopWiredRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(
        f"{SHOPWIRED_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # ShopWired rate limits with a leaky bucket (burst 40, 2 req/s sustained) and returns 429 when
    # exceeded; the exponential backoff drains the bucket before the next attempt.
    if response.status_code == 429 or response.status_code >= 500:
        raise ShopWiredRetryableError(f"ShopWired API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"ShopWired API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # ShopWired list endpoints return a bare JSON array with no wrapper or pagination metadata.
    if not isinstance(data, list):
        raise ShopWiredRetryableError(f"ShopWired returned an unexpected payload for {path}: {type(data).__name__}")

    return data


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShopWiredResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SHOPWIRED_ENDPOINTS[endpoint]
    session = _make_session(api_key, api_secret)

    if not config.paginated:
        # No documented pagination params (order statuses) — one request returns the full list.
        items = _fetch_page(session, config.path, {}, logger)
        if items:
            yield items
        return

    from_timestamp = to_unix_timestamp(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume:
        # Keep the interrupted run's `from` window so the saved offset still points at the same rows.
        from_timestamp = resume.from_timestamp
        logger.debug(f"ShopWired: resuming {endpoint} from offset {offset}")

    while True:
        params: dict[str, Any] = {"count": PAGE_SIZE, "offset": offset}
        if config.sort_param is not None:
            params["sort"] = config.sort_param
        if from_timestamp is not None:
            # Server-side created-date filter (UNIX timestamp). Assumed inclusive, so the watermark
            # row is re-fetched and deduped by the merge on `id`.
            params["from"] = from_timestamp

        items = _fetch_page(session, config.path, params, logger)
        if items:
            yield items

        # A short (or empty) page means we've reached the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        offset += len(items)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(ShopWiredResumeConfig(offset=offset, from_timestamp=from_timestamp))


def shopwired_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShopWiredResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SHOPWIRED_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_secret=api_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value if should_use_incremental_field else None,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def check_access(api_key: str, api_secret: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key/secret pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = _make_session(api_key, api_secret)
    try:
        response = session.get(f"{SHOPWIRED_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to ShopWired: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"ShopWired returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, api_secret: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, api_secret)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid ShopWired API key or secret"
    return False, message or "Could not validate ShopWired credentials"
