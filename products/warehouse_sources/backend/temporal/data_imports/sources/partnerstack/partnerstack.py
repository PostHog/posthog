import base64
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import (
    PARTNERSTACK_ENDPOINTS,
)

PARTNERSTACK_BASE_URL = "https://api.partnerstack.com/api/v2"
# The Vendor API caps `limit` at 250; the largest page minimises round trips.
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm the key pair is genuine. The credentials are account-wide, so one
# probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/partnerships"
# Cursor pagination keys on each object's `key`, which is also the primary key of every object.
CURSOR_FIELD = "key"


class PartnerStackRetryableError(Exception):
    pass


@dataclasses.dataclass
class PartnerStackResumeConfig:
    # The `key` of the last object yielded. On resume the next request passes it as `starting_after`,
    # so a crashed full-refresh sync continues after the last object persisted; merge dedupes on `key`.
    starting_after: str | None = None


def _headers(public_key: str, private_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{public_key}:{private_key}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((PartnerStackRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    starting_after: str | None,
    limit: int,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], bool]:
    params: dict[str, Any] = {"limit": limit}
    if starting_after is not None:
        params["starting_after"] = starting_after

    response = session.get(
        f"{PARTNERSTACK_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise PartnerStackRetryableError(
            f"PartnerStack API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"PartnerStack API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    body = response.json()
    # The Vendor API wraps rows under `data.items` and signals continuation with `data.has_more`.
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise PartnerStackRetryableError(
            f"PartnerStack returned an unexpected payload for {path}: {type(body).__name__}"
        )
    data = body["data"]
    items = data.get("items")
    if not isinstance(items, list):
        raise PartnerStackRetryableError(
            f"PartnerStack returned a non-list items field for {path}: {type(items).__name__}"
        )
    return items, bool(data.get("has_more", False))


def get_rows(
    public_key: str,
    private_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PartnerStackResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PARTNERSTACK_ENDPOINTS[endpoint]
    session = make_tracked_session(
        headers=_headers(public_key, private_key),
        redact_values=(public_key, private_key),
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    starting_after = resume.starting_after if resume else None
    if starting_after is not None:
        logger.debug(f"PartnerStack: resuming {endpoint} after cursor {starting_after}")

    while True:
        items, has_more = _fetch_page(session, config.path, starting_after, PAGE_SIZE, logger)
        if items:
            yield items

        # An empty page or a cleared `has_more` flag means we've reached the end of the collection.
        if not items or not has_more:
            break

        starting_after = items[-1].get(CURSOR_FIELD)
        if starting_after is None:
            # Without a cursor from the last object we cannot advance safely, so stop.
            logger.warning(f"PartnerStack: {endpoint} object missing '{CURSOR_FIELD}', stopping pagination")
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PartnerStackResumeConfig(starting_after=starting_after))


def partnerstack_source(
    public_key: str,
    private_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PartnerStackResumeConfig],
) -> SourceResponse:
    config = PARTNERSTACK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            public_key=public_key,
            private_key=private_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(public_key: str, private_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers=_headers(public_key, private_key),
        redact_values=(public_key, private_key),
    )
    try:
        response = session.get(f"{PARTNERSTACK_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to PartnerStack: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"PartnerStack returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(public_key: str, private_key: str) -> tuple[bool, str | None]:
    status, message = check_access(public_key, private_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid PartnerStack API keys"
    return False, message or "Could not validate PartnerStack API keys"
