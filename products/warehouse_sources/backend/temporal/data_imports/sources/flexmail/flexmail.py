import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import FLEXMAIL_ENDPOINTS

FLEXMAIL_BASE_URL = "https://api.flexmail.eu"
# List endpoints accept a `limit` of up to 500; the largest page minimises round trips against the
# 60 requests/minute rate limit.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
# Cheap list endpoint used to confirm the credentials are genuine. Personal access tokens are
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/sources"


class FlexmailRetryableError(Exception):
    pass


@dataclasses.dataclass
class FlexmailResumeConfig:
    # Offset of the next page to fetch. Flexmail paginates with `limit`/`offset` query params, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes the
    # re-pulled page on `id`. `0` means start from the first page.
    offset: int = 0


def _make_session(account_id: str, personal_access_token: str) -> requests.Session:
    # HTTP Basic auth: account ID as username, personal access token as password.
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(personal_access_token,))
    session.auth = (account_id, personal_access_token)
    return session


def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Flexmail responses follow HAL: records sit in `_embedded.item`, which is omitted when the
    # collection is empty. Per-item `_links` are navigation noise, not data, so we drop them.
    embedded = data.get("_embedded")
    items = embedded.get("item") if isinstance(embedded, dict) else None
    if not isinstance(items, list):
        return []
    return [{k: v for k, v in item.items() if k != "_links"} if isinstance(item, dict) else item for item in items]


@retry(
    retry=retry_if_exception_type((FlexmailRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(6),
    # Rate limiting is a fixed 60 requests/minute cycle, so the backoff must be able to span a full
    # minute before giving up.
    wait=wait_exponential_jitter(initial=5, max=70),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any] | None,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{FLEXMAIL_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise FlexmailRetryableError(f"Flexmail API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Flexmail API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise FlexmailRetryableError(f"Flexmail returned an unexpected payload for {path}: {type(data).__name__}")

    return data


def get_rows(
    account_id: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlexmailResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FLEXMAIL_ENDPOINTS[endpoint]
    session = _make_session(account_id, personal_access_token)

    if not config.paginated:
        # Segments, opt-in forms and custom fields return the full collection in one response.
        data = _fetch_page(session, config.path, None, logger)
        items = _extract_items(data)
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset:
        logger.debug(f"Flexmail: resuming {endpoint} from offset {offset}")

    while True:
        data = _fetch_page(session, config.path, {"limit": PAGE_SIZE, "offset": offset}, logger)
        items = _extract_items(data)
        if items:
            yield items

        # The collection envelope carries `total`; we've reached the end once the next offset passes
        # it (or the page came back empty, e.g. rows deleted mid-sync shrank the collection).
        total = data.get("total")
        next_offset = offset + PAGE_SIZE
        if not items or not isinstance(total, int) or next_offset >= total:
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(FlexmailResumeConfig(offset=next_offset))
        offset = next_offset


def flexmail_source(
    account_id: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlexmailResumeConfig],
) -> SourceResponse:
    config = FLEXMAIL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account_id=account_id,
            personal_access_token=personal_access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(
    account_id: str, personal_access_token: str, path: str = DEFAULT_PROBE_PATH
) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = _make_session(account_id, personal_access_token)
    try:
        response = session.get(f"{FLEXMAIL_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Flexmail: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Flexmail returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(account_id: str, personal_access_token: str) -> tuple[bool, str | None]:
    status, message = check_access(account_id, personal_access_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flexmail account ID or personal access token"
    return False, message or "Could not validate Flexmail credentials"
