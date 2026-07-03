import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.settings import INTRUDER_ENDPOINTS

INTRUDER_BASE_URL = "https://api.intruder.io/v1"
# Intruder caps authenticated requests at 5000/hour, so we page as large as the API allows to keep
# the request count down. Its list endpoints default to 25 per page and accept a `limit` param.
PAGE_SIZE = 100

_ALLOWED_URL = urlsplit(INTRUDER_BASE_URL)


class IntruderRetryableError(Exception):
    pass


def _validate_url(url: str) -> str:
    """Reject any request URL that isn't on the Intruder API origin.

    Pagination `next` URLs — and the resumed cursor loaded from Redis state — come from data we
    don't fully trust. A poisoned resume value or a malicious `next` returned by the API (or an
    intermediary) would otherwise make the worker send the customer's `Authorization: Bearer ...`
    header to an attacker-controlled host, leaking the token (SSRF). Only allow the exact
    `https://api.intruder.io/v1/...` origin through.
    """
    parts = urlsplit(url)
    if (
        parts.scheme != _ALLOWED_URL.scheme
        or parts.netloc != _ALLOWED_URL.netloc
        or not parts.path.startswith(f"{_ALLOWED_URL.path}/")
    ):
        raise ValueError(f"Refusing to follow non-Intruder URL: {url}")
    return url


@dataclasses.dataclass
class IntruderResumeConfig:
    # Full URL of the next page to fetch. Intruder returns a ready-to-follow `next` URL on every
    # paginated response. None means "start this endpoint (or fan-out issue) from its first page".
    next_url: str | None = None
    # The issue currently being processed in the occurrences fan-out. A stable issue-ID bookmark
    # (not a positional index) so issues added/removed between a crash and the retry can't resume us
    # into the wrong issue. None for the standard (non-fan-out) endpoints.
    issue_id: int | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _initial_url(path: str) -> str:
    # First request for a collection; every subsequent page is fetched by following the `next` URL
    # the API returns, which already carries the limit/offset.
    return f"{INTRUDER_BASE_URL}{path}?limit={PAGE_SIZE}"


def validate_credentials(access_token: str) -> bool:
    # `/targets/` requires a valid token (401 otherwise) and returns 200 even for accounts with no
    # targets, making it a cheap, side-effect-free probe. `/health/` can't be used for this — it
    # returns 200 regardless of whether the token is valid.
    url = f"{INTRUDER_BASE_URL}/targets/"
    try:
        response = make_tracked_session(redact_values=(access_token,)).get(
            url, headers=_get_headers(access_token), params={"limit": 1}, timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            IntruderRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    # Validate before every request (not just on save/resume) so the origin allowlist is the single
    # choke point covering initial, resumed, and API-returned `next` URLs. `allow_redirects=False`
    # stops a 3xx from retargeting the authenticated request at another host.
    response = session.get(_validate_url(url), headers=headers, timeout=60, allow_redirects=False)

    # Pagination is driven by `next` URLs in the body, never HTTP redirects; an unexpected redirect
    # is refused rather than followed, so the bearer token can't be forwarded off-origin.
    if response.is_redirect:
        raise requests.HTTPError(
            f"Intruder API returned an unexpected redirect: status={response.status_code}, url={url}"
        )

    # 429 (rate limit) and 5xx are transient — back off and retry rather than fail the whole sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise IntruderRetryableError(f"Intruder API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Intruder API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_issue_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[int]:
    """Page through `/issues/` and yield each issue's id, following the `next` links."""
    url = _initial_url(INTRUDER_ENDPOINTS["issues"].path)
    while True:
        data = _fetch_page(session, url, headers, logger)
        for item in data.get("results", []):
            yield item["id"]
        next_url = data.get("next")
        if not next_url:
            break
        url = next_url


def _get_occurrence_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every issue, materializing its occurrences as rows tagged with `issue_id`.

    Full refresh only — the occurrences endpoint has no verifiable server-side incremental filter —
    so re-pulled rows on resume are deduped by the `[issue_id, id]` primary key on merge.
    """
    issue_ids = list(_iter_issue_ids(session, headers, logger))

    # Resolve the saved issue-ID bookmark to the slice of issues still to process. If the bookmarked
    # issue no longer exists (deleted between runs), start over from the first issue — merge dedupes
    # the re-pulled rows on the primary key. `resume_url` is consumed by the resumed-into issue only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = issue_ids
    resume_url: str | None = None
    if resume is not None and resume.issue_id is not None and resume.issue_id in issue_ids:
        remaining = issue_ids[issue_ids.index(resume.issue_id) :]
        resume_url = resume.next_url
        logger.debug(f"Intruder: resuming occurrences from issue_id={resume.issue_id}, url={resume_url}")

    for index, issue_id in enumerate(remaining):
        path = INTRUDER_ENDPOINTS["occurrences"].path.format(issue_id=issue_id)
        url = resume_url or _initial_url(path)
        resume_url = None  # only the resumed-into issue uses the saved URL; the rest start fresh

        while True:
            data = _fetch_page(session, url, headers, logger)
            # Tag each occurrence with its parent issue so `[issue_id, id]` is unique table-wide.
            results = [{**item, "issue_id": issue_id} for item in data.get("results", [])]
            if results:
                yield results

            next_url = data.get("next")
            if not next_url:
                break
            # Save AFTER yielding so a crash re-yields the last page (merge dedupes) rather than
            # skipping it.
            resumable_source_manager.save_state(IntruderResumeConfig(next_url=next_url, issue_id=issue_id))
            url = next_url

        # Advance the bookmark to the next issue so a crash between issues resumes correctly. Its
        # first page URL is rebuilt when the loop reaches it.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(IntruderResumeConfig(next_url=None, issue_id=remaining[index + 1]))


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = INTRUDER_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    # One session reused across every page (and, for the fan-out, every issue) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. `retry=Retry(total=0)` disables the
    # adapter's own retries so tenacity in `_fetch_page` is the single retry authority;
    # `redact_values` masks the bearer token in logged URLs and captured samples.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(access_token,))

    if config.fan_out_over_issues:
        yield from _get_occurrence_rows(session, headers, logger, resumable_source_manager)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Intruder: resuming {endpoint} from URL: {url}")
    else:
        url = _initial_url(config.path)

    while True:
        data = _fetch_page(session, url, headers, logger)
        results = data.get("results", [])
        if results:
            yield results

        next_url = data.get("next")
        if not next_url:
            break
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes) rather than skipping it.
        resumable_source_manager.save_state(IntruderResumeConfig(next_url=next_url))
        url = next_url


def intruder_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
) -> SourceResponse:
    config = INTRUDER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
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
