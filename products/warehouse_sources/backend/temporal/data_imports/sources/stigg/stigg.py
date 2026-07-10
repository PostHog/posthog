import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.settings import STIGG_ENDPOINTS

STIGG_BASE_URL = "https://api.stigg.io/api/v1"
# List endpoints accept a `limit` of up to 100 (default 20); the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. Server API keys are environment-wide,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/customers"


class StiggRetryableError(Exception):
    pass


@dataclasses.dataclass
class StiggResumeConfig:
    # Cursor for the next page: Stigg returns it as `pagination.next` and accepts it back as
    # the `after` query param. A crashed full-refresh sync resumes from the page after the last
    # one yielded; merge dedupes the re-pulled page on the primary key. `None` means start from
    # the first page.
    cursor: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((StiggRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    cursor: str | None,
    limit: int,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, Any] = {"limit": limit}
    if cursor is not None:
        params["after"] = cursor

    response = session.get(
        f"{STIGG_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise StiggRetryableError(f"Stigg API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Stigg API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Stigg list endpoints wrap records in {"data": [...], "pagination": {"next": ..., "prev": ...}}.
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise StiggRetryableError(f"Stigg returned an unexpected payload for {path}: {type(data).__name__}")

    items: list[dict[str, Any]] = data["data"]
    pagination = data.get("pagination") or {}
    next_cursor = pagination.get("next") if isinstance(pagination, dict) else None
    return items, next_cursor


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StiggResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = STIGG_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if resume and resume.cursor is not None:
        logger.debug(f"Stigg: resuming {endpoint} from cursor {cursor}")

    while True:
        items, next_cursor = _fetch_page(session, config.path, cursor, PAGE_SIZE, logger)
        if items:
            yield items

        # A null `pagination.next` (or an empty page) means we've reached the end of the list.
        if not next_cursor or not items:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(StiggResumeConfig(cursor=cursor))


def stigg_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StiggResumeConfig],
) -> SourceResponse:
    config = STIGG_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{STIGG_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Stigg: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Stigg returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys."
    return False, message or "Could not validate Stigg API key"
