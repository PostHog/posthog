import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import RESPONSES_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")

# Unix-timestamp fields AskNicely returns as strings; coerced to ints so the incremental
# watermark comparison and datetime partitioning work numerically.
TIMESTAMP_FIELDS = ("sent", "opened", "responded", "lastemailed", "created", "case_closed_time")

REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class AskNicelyResumeConfig:
    # 1-based next page to fetch. Page numbering is only stable relative to the since_time
    # cutoff the run started with, so the cutoff is persisted alongside it.
    page_number: int
    since_time: int


def _base_url(subdomain: str) -> str:
    # Each AskNicely customer gets their own subdomain of asknice.ly, so only the label needs
    # validating — the credential can never be sent to a host outside AskNicely's domain.
    if not SUBDOMAIN_REGEX.match(subdomain):
        raise ValueError(f"Invalid AskNicely subdomain: {subdomain!r}")
    return f"https://{subdomain}.asknice.ly"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-apikey": api_key, "Accept": "application/json"}


def build_responses_url(subdomain: str, page_number: int, since_time: int, page_size: int = RESPONSES_PAGE_SIZE) -> str:
    """Build the path-segment-paginated responses URL.

    Segments: /responses/{sort_direction}/{pagesize}/{pagenumber}/{since_time}/{format}/{filter}/{sort_by}.
    `answered` restricts rows to actual survey responses (vs sent-but-unanswered), and
    `responded` keys both the sort and the since_time cutoff to the response timestamp,
    matching the advertised incremental field. Ascending sort keeps earlier pages stable
    while new responses land on the tail.
    """
    return f"{_base_url(subdomain)}/api/v1/responses/asc/{page_size}/{page_number}/{since_time}/json/answered/responded"


def _to_unix_timestamp(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Cannot convert incremental field value to a unix timestamp: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    raise ValueError(f"Cannot convert incremental field value to a unix timestamp: {value!r}")


def _parse_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    for field in TIMESTAMP_FIELDS:
        value = row.get(field)
        if isinstance(value, str) and value.strip().isdigit():
            row[field] = int(value.strip())
    return row


@retry(
    # Transient connection breaks only — 429/5xx status retries are already handled with
    # backoff by the tracked session's urllib3 Retry policy.
    retry=retry_if_exception_type(
        (requests.ReadTimeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if not response.ok:
        logger.error(f"AskNicely API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    subdomain: str,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every page so urllib3 keeps the connection alive.
    # `capture=False`: response rows carry free-text survey comments and internal notes the
    # name-based sample scrubbers can't recognise, so keep bodies out of HTTP sample storage
    # entirely. Requests are still metered and logged (status + url).
    session = make_tracked_session(redact_values=(api_key,), capture=False)
    headers = _get_headers(api_key)

    since_time = 0
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # The docs don't state whether since_time is inclusive; step back one second so a
        # boundary-second response is never skipped — merge dedupes re-pulled rows on response_id.
        since_time = max(_to_unix_timestamp(db_incremental_field_last_value) - 1, 0)

    page_number = 1
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        # Page numbering is only stable against the cutoff the interrupted run used, so resume
        # with the saved since_time rather than a freshly derived one.
        page_number = resume.page_number
        since_time = resume.since_time
        logger.debug(f"AskNicely: resuming responses from page {page_number} (since_time={since_time})")

    while True:
        url = build_responses_url(subdomain, page_number, since_time)
        data = _fetch_page(session, url, headers, logger)
        items = data.get("data") or []
        if not items:
            break

        yield [_normalize_row(item) for item in items]

        total_pages = _parse_int(data.get("totalpages"))
        if total_pages is not None and page_number >= total_pages:
            break
        if total_pages is None and len(items) < RESPONSES_PAGE_SIZE:
            break

        page_number += 1
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(AskNicelyResumeConfig(page_number=page_number, since_time=since_time))


def asknicely_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_key=api_key,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["response_id"],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        # `responded` is set once when the customer answers, so partitions never rewrite.
        partition_keys=["responded"],
    )


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, str | None]:
    try:
        # `capture=False`: the probe fetches a real response row, whose free-text fields must
        # stay out of HTTP sample storage just like the sync path's.
        response = make_tracked_session(redact_values=(api_key,), capture=False).get(
            build_responses_url(subdomain, page_number=1, since_time=0, page_size=1),
            headers=_get_headers(api_key),
            timeout=30,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid AskNicely API key. You can find your API key in AskNicely under Settings > API."
    return False, f"AskNicely returned an unexpected status code: {response.status_code}"
