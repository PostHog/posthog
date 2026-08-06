import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    MAX_PAGE_SIZE,
    TRUSTPILOT_ENDPOINTS,
    TrustpilotEndpointConfig,
)

BASE_URL = "https://api.trustpilot.com/v1"
API_HOST = "api.trustpilot.com"

REQUEST_TIMEOUT_SECONDS = 60
CREDENTIALS_TIMEOUT_SECONDS = 15

# Hard cap on pages walked for one list endpoint so a pagination bug can't scan forever. At 100 rows
# a page that is 1,000,000 rows.
MAX_PAGES_PER_RESOURCE = 10_000


class TrustpilotUrlError(Exception):
    """A request URL points somewhere other than the Trustpilot API origin."""


def _require_api_url(url: str) -> str:
    """Reject any URL that isn't ``https://api.trustpilot.com`` on the default HTTPS port.

    Every outbound request carries the customer's Trustpilot API key in a header, so pinning the host
    keeps a mistyped path or future refactor from sending that key anywhere but Trustpilot.
    """
    try:
        parts = urlsplit(url)
    except Exception as e:
        raise TrustpilotUrlError(f"Unparseable Trustpilot URL: {url!r}") from e

    if parts.scheme != "https" or parts.hostname != API_HOST or parts.port not in (None, 443):
        raise TrustpilotUrlError(f"Refusing to request a non-Trustpilot URL: {url!r}")
    return url


@dataclasses.dataclass
class TrustpilotResumeConfig:
    # The next 1-based page to fetch for a paginated list. Business units aren't paginated, so their
    # runs never persist a bookmark.
    next_page: int | None = None


def _make_session(api_key: str) -> requests.Session:
    # Redirects stay off so a 3xx can't quietly forward an api-key-bearing request to another host.
    return make_tracked_session(
        headers={"apikey": api_key, "Accept": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _get(
    session: requests.Session,
    url: str,
    *,
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    tolerate: tuple[int, ...] = (),
) -> requests.Response:
    """GET a Trustpilot URL. 429 and transient 5xx are already retried by the tracked adapter."""
    _require_api_url(url)

    response = session.get(url, params=params, timeout=timeout)

    if 300 <= response.status_code < 400:
        # Redirects are pinned off on the session, so a 3xx is Trustpilot's origin (or something posing
        # as it) trying to forward the request elsewhere. Fail closed rather than chase it with a key.
        logger.error(f"Trustpilot unexpected redirect: status={response.status_code}, url={url}")
        raise TrustpilotUrlError(f"Unexpected redirect from Trustpilot: {url!r}")

    if response.status_code in tolerate:
        return response

    if not response.ok:
        logger.error(f"Trustpilot API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response


def _load_resume(manager: ResumableSourceManager[TrustpilotResumeConfig]) -> TrustpilotResumeConfig | None:
    return manager.load_state() if manager.can_resume() else None


def _iter_pages(
    session: requests.Session,
    config: TrustpilotEndpointConfig,
    logger: FilteringBoundLogger,
    business_unit_id: str,
    manager: ResumableSourceManager[TrustpilotResumeConfig],
) -> Iterator[tuple[list[dict[str, Any]], int]]:
    """Walk a paginated list forward, yielding each page's rows plus the page number it came from.

    Pagination is 1-based ``page``/``perPage``. Trustpilot returns a short (or empty) page once the
    list is exhausted, so a page smaller than ``perPage`` is the last one.
    """
    url = f"{BASE_URL}{config.path.format(business_unit_id=business_unit_id)}"

    resume = _load_resume(manager)
    page = resume.next_page if resume is not None and resume.next_page else 1

    walked = 0
    while True:
        body = _get(
            session,
            url,
            logger=logger,
            params={**config.params, "page": page, "perPage": MAX_PAGE_SIZE},
        ).json()
        data = body.get(config.data_key) if isinstance(body, dict) else None
        rows = [row for row in (data or []) if isinstance(row, dict)]

        yield rows, page

        walked += 1
        if len(rows) < MAX_PAGE_SIZE:
            return
        if walked >= MAX_PAGES_PER_RESOURCE:
            logger.warning(
                f"Trustpilot: page cap reached, truncating {config.name}. business_unit_id={business_unit_id}"
            )
            return

        page += 1
        # Save AFTER yielding so a crash re-fetches the page we just emitted rather than skipping it;
        # merge dedupes the re-pulled rows on the primary key.
        manager.save_state(TrustpilotResumeConfig(next_page=page))


def _to_reply_row(review: dict[str, Any], business_unit_id: str) -> dict[str, Any] | None:
    """Lift a service review's embedded ``companyReply`` into a standalone reply row, or ``None``."""
    reply = review.get("companyReply")
    review_id = review.get("id")
    if not isinstance(reply, dict) or not review_id:
        return None
    return {
        "review_id": review_id,
        "business_unit_id": business_unit_id,
        "text": reply.get("text"),
        "createdAt": reply.get("createdAt"),
        "updatedAt": reply.get("updatedAt"),
    }


def get_rows(
    api_key: str,
    business_unit_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TrustpilotResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = TRUSTPILOT_ENDPOINTS[endpoint]
    session = _make_session(api_key)

    if config.kind == "single":
        url = f"{BASE_URL}{config.path.format(business_unit_id=business_unit_id)}"
        body = _get(session, url, logger=logger).json()
        if isinstance(body, dict):
            yield [body]
    elif config.kind == "paginated":
        for rows, _page in _iter_pages(session, config, logger, business_unit_id, resumable_source_manager):
            if rows:
                yield rows
    else:  # "review_replies"
        for rows, _page in _iter_pages(session, config, logger, business_unit_id, resumable_source_manager):
            replies = [reply for review in rows if (reply := _to_reply_row(review, business_unit_id)) is not None]
            if replies:
                yield replies

    # Walked to completion, so drop the checkpoint — leaving it would let a later attempt on this job
    # resume mid-stream instead of restarting cleanly.
    resumable_source_manager.clear_state()


def check_credentials(api_key: str, business_unit_id: str) -> tuple[int | None, str | None]:
    """Probe the configured business unit with the API key.

    Returns ``(http_status, message)``. The status is ``None`` when the request never left the process
    (a network failure), in which case ``message`` explains why when we know.
    """
    try:
        response = _make_session(api_key).get(
            f"{BASE_URL}/business-units/{business_unit_id}",
            timeout=CREDENTIALS_TIMEOUT_SECONDS,
        )
        return response.status_code, None
    except Exception:
        return None, None


def trustpilot_source(
    api_key: str,
    business_unit_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TrustpilotResumeConfig],
) -> SourceResponse:
    config = TRUSTPILOT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            business_unit_id=business_unit_id,
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
        # Every table is a full refresh merged on a unique key, so page order doesn't affect the result.
        sort_mode="asc",
    )


__all__ = [
    "BASE_URL",
    "TrustpilotResumeConfig",
    "TrustpilotUrlError",
    "check_credentials",
    "get_rows",
    "trustpilot_source",
]
