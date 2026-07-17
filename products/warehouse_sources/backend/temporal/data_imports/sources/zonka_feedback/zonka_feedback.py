import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.settings import (
    ZONKA_FEEDBACK_ENDPOINTS,
)

# Zonka Feedback hosts data per region; the account's data center is the subdomain of the API host.
# US=us1, EU=e, IN=in are the documented, verifiable identifiers.
DATA_CENTER_IDS: tuple[str, ...] = ("us1", "e", "in")
# The list endpoints default to 25 items per page and allow overriding the page size. We request a
# larger page to cut round trips; pagination terminates on the first empty page, so the request is
# correct whether or not the server honours the larger size.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an auth token is genuine. The admin-generated token is account-wide,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/surveys"


class ZonkaFeedbackRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZonkaFeedbackResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def base_url(data_center: str) -> str:
    # Validate against the fixed allowlist before interpolating: a `data_center` carrying URL
    # delimiters (`/`, `#`, `@`) could otherwise retarget the request at an attacker host and leak
    # the bearer token during validation or sync.
    if data_center not in DATA_CENTER_IDS:
        raise ValueError("Unknown Zonka Feedback data center")
    return f"https://{data_center}.apis.zonkafeedback.com"


def _headers(auth_token: str) -> dict[str, str]:
    # Zonka Feedback expects the admin-generated auth token as a Bearer credential.
    return {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((ZonkaFeedbackRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    page: int,
    page_size: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        url,
        params={"page": page, "page_size": page_size},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise ZonkaFeedbackRetryableError(
            f"Zonka Feedback API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        # Don't log `response.text`: error bodies from these endpoints can echo contact/feedback PII
        # into logs that sit outside the warehouse tables' access controls. Status and the redacted
        # URL are enough to diagnose.
        logger.error(f"Zonka Feedback API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    auth_token: str,
    data_center: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZonkaFeedbackResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZONKA_FEEDBACK_ENDPOINTS[endpoint]
    url = f"{base_url(data_center)}{config.path}"
    # `redact_values` masks the auth token in logged URLs and captured samples. `allow_redirects=False`
    # pins the credentialed request to the validated Zonka Feedback host so a 3xx from a compromised
    # or misconfigured endpoint can't retarget the bearer token at another origin.
    session = make_tracked_session(headers=_headers(auth_token), redact_values=(auth_token,), allow_redirects=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"Zonka Feedback: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, url, page, PAGE_SIZE, logger)

        # `result` is the documented envelope key for paginated list endpoints; missing it means a
        # malformed response, so fail loudly rather than silently advancing past lost rows.
        rows = data["result"]

        # There is no `has_more` flag, and the server may cap the page size below what we request, so
        # short pages are not a reliable stop signal — terminate on the first empty page instead.
        if not rows:
            break

        yield rows

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(ZonkaFeedbackResumeConfig(next_page=page))


def zonka_feedback_source(
    auth_token: str,
    data_center: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZonkaFeedbackResumeConfig],
) -> SourceResponse:
    config = ZONKA_FEEDBACK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth_token=auth_token,
            data_center=data_center,
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


def check_access(auth_token: str, data_center: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the auth token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(auth_token), redact_values=(auth_token,), allow_redirects=False)
    try:
        response = session.get(f"{base_url(data_center)}{path}", params={"page": 1, "page_size": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Zonka Feedback: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Zonka Feedback returned HTTP {response.status_code}"

    return 200, None
