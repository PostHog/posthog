import time
import base64
import dataclasses
from bisect import bisect_left
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.settings import PHYLLO_ENDPOINTS

# Credentials are environment-specific: a sandbox client ID/secret pair only authenticates against
# the sandbox host, so the environment select on the source form picks the base URL.
PHYLLO_BASE_URLS: dict[str, str] = {
    "production": "https://api.getphyllo.com",
    "sandbox": "https://api.sandbox.getphyllo.com",
}
# Documented maximum page size for Phyllo list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Phyllo rate-limits at 10 requests/second per developer account and returns a Retry-After header
# on 429; cap how long we honor it before exponential backoff takes over.
MAX_RETRY_AFTER_SECONDS = 60
ACCOUNTS_PATH = "/v1/accounts"
# Cheap list endpoint used to confirm a client ID/secret pair is genuine. Phyllo credentials are
# environment-wide, so one probe validates access to every endpoint.
DEFAULT_PROBE_PATH = "/v1/work-platforms"


class PhylloRetryableError(Exception):
    pass


@dataclasses.dataclass
class PhylloResumeConfig:
    # Offset of the next page within the current stream. Limit-offset pagination is deterministic,
    # so a crashed sync resumes from the page after the last one yielded; merge dedupes the
    # re-pulled page on `id`.
    offset: int = 0
    # For per-account fan-out endpoints: the account whose rows were being fetched when state was
    # last saved. None for top-level endpoints.
    account_id: str | None = None


def get_base_url(environment: str) -> str:
    return PHYLLO_BASE_URLS.get(environment, PHYLLO_BASE_URLS["production"])


def _headers(client_id: str, client_secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


@retry(
    retry=retry_if_exception_type((PhylloRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                time.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
        raise PhylloRetryableError(f"Phyllo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Phyllo API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Phyllo list endpoints wrap results in {"data": [...], "metadata": {...}}.
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise PhylloRetryableError(f"Phyllo returned an unexpected payload for {url}: {type(data).__name__}")

    return data["data"]


def _list_account_ids(
    session: requests.Session,
    base_url: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    """Collect every connected account id, sorted so fan-out iteration order is deterministic."""
    account_ids: list[str] = []
    offset = 0
    while True:
        items = _fetch_page(session, f"{base_url}{ACCOUNTS_PATH}", {"limit": PAGE_SIZE, "offset": offset}, logger)
        # `id` is the primary key of an account record — index it directly so a malformed record
        # fails the sync loudly instead of silently dropping the account's child rows.
        account_ids.extend(item["id"] for item in items)
        if len(items) < PAGE_SIZE:
            break
        offset += len(items)
    return sorted(account_ids)


def _get_top_level_rows(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PhylloResumeConfig],
    resume: PhylloResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    offset = resume.offset if resume else 0

    while True:
        items = _fetch_page(session, url, {"limit": PAGE_SIZE, "offset": offset}, logger)
        if items:
            yield items

        # A short page marks the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        offset += len(items)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PhylloResumeConfig(offset=offset))


def _get_fan_out_rows(
    session: requests.Session,
    base_url: str,
    url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PhylloResumeConfig],
    resume: PhylloResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    account_ids = _list_account_ids(session, base_url, logger)

    start_index = 0
    offset = 0
    if resume and resume.account_id is not None:
        # Accounts iterate in sorted order, so resume skips straight to the saved account. If it
        # has since been disconnected we continue from the next account after it.
        start_index = bisect_left(account_ids, resume.account_id)
        if start_index < len(account_ids) and account_ids[start_index] == resume.account_id:
            offset = resume.offset

    for index in range(start_index, len(account_ids)):
        account_id = account_ids[index]

        while True:
            items = _fetch_page(session, url, {"account_id": account_id, "limit": PAGE_SIZE, "offset": offset}, logger)
            if items:
                yield items

            if len(items) < PAGE_SIZE:
                break

            offset += len(items)
            resumable_source_manager.save_state(PhylloResumeConfig(offset=offset, account_id=account_id))

        offset = 0
        if index + 1 < len(account_ids):
            # Advance the checkpoint past the completed account so a crash before the next
            # account's first save doesn't replay the account we just finished.
            resumable_source_manager.save_state(PhylloResumeConfig(offset=0, account_id=account_ids[index + 1]))


def get_rows(
    client_id: str,
    client_secret: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PhylloResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PHYLLO_ENDPOINTS[endpoint]
    base_url = get_base_url(environment)
    session = make_tracked_session(headers=_headers(client_id, client_secret), redact_values=(client_secret,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume:
        logger.debug(f"Phyllo: resuming {endpoint} from account_id={resume.account_id}, offset={resume.offset}")

    url = f"{base_url}{config.path}"
    if config.fan_out_by_account:
        yield from _get_fan_out_rows(session, base_url, url, logger, resumable_source_manager, resume)
    else:
        yield from _get_top_level_rows(session, url, logger, resumable_source_manager, resume)


def phyllo_source(
    client_id: str,
    client_secret: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PhylloResumeConfig],
) -> SourceResponse:
    config = PHYLLO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            environment=environment,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(
    client_id: str, client_secret: str, environment: str, path: str = DEFAULT_PROBE_PATH
) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the client ID/secret pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(client_id, client_secret), redact_values=(client_secret,))
    try:
        response = session.get(f"{get_base_url(environment)}{path}", params={"limit": 1, "offset": 0}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Phyllo: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Phyllo returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(client_id: str, client_secret: str, environment: str) -> tuple[bool, str | None]:
    status, message = check_access(client_id, client_secret, environment)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Phyllo client ID or secret for the selected environment"
    return False, message or "Could not validate Phyllo credentials"
