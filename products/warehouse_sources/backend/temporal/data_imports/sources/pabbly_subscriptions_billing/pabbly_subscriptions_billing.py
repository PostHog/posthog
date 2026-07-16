import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.settings import (
    PABBLY_ENDPOINTS,
    PabblyEndpointConfig,
)

PABBLY_BASE_URL = "https://payments.pabbly.com/api/v1"
# List endpoints accept `limit` up to 100 (default 50); the largest page minimises round trips
# against the account's 10,000 requests/day quota.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm the API key + secret key pair is genuine. The pair is
# account-wide, so one probe validates access to every endpoint.
DEFAULT_PROBE_PATH = "/customers"


class PabblyRetryableError(Exception):
    pass


@dataclasses.dataclass
class PabblyResumeConfig:
    # Next `page` to fetch. For top-level endpoints this is the endpoint's own page; for fan-out
    # children it is the PARENT listing's page — a crashed sync resumes from the first parent page
    # whose children weren't all yielded, and merge dedupes re-pulled rows on the primary key.
    page: int = 1


def _make_session(api_key: str, secret_key: str, capture: bool = True) -> requests.Session:
    # Pabbly authenticates with HTTP Basic only: API key as username, secret key as password.
    # (Its docs portal shows a generic Bearer example, but the live API rejects Bearer tokens.)
    session = make_tracked_session(
        headers={"Accept": "application/json"}, redact_values=(api_key, secret_key), capture=capture
    )
    session.auth = (api_key, secret_key)
    return session


def _is_no_data_message(message: str) -> bool:
    # Pabbly signals "this resource has no rows" with messages like "No transaction found" /
    # "No data found" rather than an empty list. Auth failures ("Invalid user api") don't match.
    lowered = message.lower()
    return lowered.startswith("no ") and "found" in lowered


@retry(
    retry=retry_if_exception_type((PabblyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    limit: int,
    logger: FilteringBoundLogger,
    ignore_no_data_errors: bool,
) -> list[dict[str, Any]]:
    response = session.get(
        f"{PABBLY_BASE_URL}{path}",
        params={"page": page, "limit": limit},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise PabblyRetryableError(f"Pabbly API error (retryable): status={response.status_code}, path={path}")

    # Pabbly answers some endpoints with a 400 when the resource simply has no data (e.g. a
    # product with no addons). Its Airbyte connector ignores those the same way.
    if response.status_code == 400 and ignore_no_data_errors:
        logger.debug(f"Pabbly: treating 400 as empty page. path={path}, body={response.text[:200]}")
        return []

    if not response.ok:
        logger.error(f"Pabbly API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise PabblyRetryableError(f"Pabbly returned an unexpected payload for {path}: {type(data).__name__}")

    # Every response is wrapped in {"status": ..., "message": ..., "data": ...}. A "no data"
    # error envelope can come back with HTTP 200 too.
    if data.get("status") == "error":
        message = str(data.get("message", ""))
        if _is_no_data_message(message):
            return []
        raise ValueError(f"Pabbly API returned an error for {path}: {message}")

    rows = data.get("data")
    if rows is None:
        return []
    if isinstance(rows, dict):
        return [rows]
    if not isinstance(rows, list):
        raise PabblyRetryableError(f"Pabbly returned an unexpected data field for {path}: {type(rows).__name__}")
    return rows


def _iter_top_level(
    session: requests.Session,
    config: PabblyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PabblyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 1
    if resume:
        logger.debug(f"Pabbly: resuming {config.name} from page {page}")

    while True:
        rows = _fetch_page(session, config.path, page, PAGE_SIZE, logger, config.ignore_no_data_errors)
        if rows:
            yield rows

        # A short page means we've reached the end of the list.
        if len(rows) < PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(PabblyResumeConfig(page=page))


def _iter_children_of_parent(
    session: requests.Session,
    config: PabblyEndpointConfig,
    parent_id: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    path = config.path.format(parent_id=parent_id)
    page = 1
    while True:
        rows = _fetch_page(session, path, page, PAGE_SIZE, logger, config.ignore_no_data_errors)
        if rows:
            if config.parent_field:
                for row in rows:
                    row.setdefault(config.parent_field, parent_id)
            yield rows
        if len(rows) < PAGE_SIZE:
            break
        page += 1


def _iter_fan_out(
    session: requests.Session,
    config: PabblyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PabblyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    assert config.parent is not None
    parent_config = PABBLY_ENDPOINTS[config.parent]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    parent_page = resume.page if resume else 1
    if resume:
        logger.debug(f"Pabbly: resuming {config.name} from parent page {parent_page}")

    while True:
        parents = _fetch_page(
            session, parent_config.path, parent_page, PAGE_SIZE, logger, parent_config.ignore_no_data_errors
        )
        for parent in parents:
            parent_id = str(parent["id"])
            yield from _iter_children_of_parent(session, config, parent_id, logger)

        if len(parents) < PAGE_SIZE:
            break

        parent_page += 1
        # Save AFTER every child of this parent page has been yielded — a crash resumes from the
        # next parent page, re-pulling at most one parent page's children (merge dedupes them).
        resumable_source_manager.save_state(PabblyResumeConfig(page=parent_page))


def get_rows(
    api_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PabblyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PABBLY_ENDPOINTS[endpoint]
    session = _make_session(api_key, secret_key, capture=config.capture_http_samples)

    if config.parent is not None:
        yield from _iter_fan_out(session, config, logger, resumable_source_manager)
    else:
        yield from _iter_top_level(session, config, logger, resumable_source_manager)


def pabbly_source(
    api_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PabblyResumeConfig],
) -> SourceResponse:
    config = PABBLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            secret_key=secret_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, secret_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key + secret key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure (Pabbly
    answers invalid credentials with a 403), ``0`` for a connection problem, other HTTP
    status otherwise.
    """
    session = _make_session(api_key, secret_key)
    try:
        response = session.get(f"{PABBLY_BASE_URL}{path}", params={"page": 1, "limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Pabbly Subscription Billing: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Pabbly Subscription Billing returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, secret_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, secret_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Pabbly Subscription Billing API key or secret key"
    return False, message or "Could not validate Pabbly Subscription Billing credentials"
