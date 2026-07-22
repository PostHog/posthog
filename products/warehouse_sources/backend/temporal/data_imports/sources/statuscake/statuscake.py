import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.settings import (
    STATUSCAKE_ENDPOINTS,
    StatusCakeEndpointConfig,
)

STATUSCAKE_BASE_URL = "https://api.statuscake.com/v1"

# StatusCake rate-limits per account (60 requests/minute on free plans, 5 requests/second on paid)
# and answers HTTP 429 when exceeded. The backoff cap sits above the free plan's 60s window so a
# throttled fan-out (one request chain per test) clears rather than exhausting its retries.
_MAX_ATTEMPTS = 8
_REQUEST_TIMEOUT_SECONDS = 60
_PAGE_SIZE = 100  # documented maximum for `limit`


class StatusCakeRetryableError(Exception):
    """Raised for rate-limit (429) and transient 5xx responses so tenacity retries them."""

    pass


@dataclasses.dataclass
class StatusCakeResumeConfig:
    # Top-level list endpoints: the page number most recently yielded. On resume we re-fetch and
    # re-yield that page (merge dedupes on the primary key) rather than risk skipping rows that
    # were buffered but not yet persisted when the worker stopped.
    page: Optional[int] = None
    # Fan-out endpoints: the test id currently being read — a stable bookmark (not a positional
    # index) so tests added/removed between a crash and the retry can't resume us into the wrong
    # test. None for top-level endpoints.
    test_id: Optional[str] = None
    # Fan-out endpoints: full URL of the next history page (from the response's links.next). None
    # means "start the bookmarked test at its first page".
    next_url: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{STATUSCAKE_BASE_URL}{path}"
    return f"{base}?{urlencode(params)}" if params else base


def _scrub_rows(rows: list[dict[str, Any]], fields: Optional[list[str]]) -> list[dict[str, Any]]:
    """Drop sensitive fields (e.g. heartbeat push credentials) before rows reach the warehouse."""
    if not fields:
        return rows
    for row in rows:
        for field in fields:
            row.pop(field, None)
    return rows


def _is_api_url(url: Any) -> bool:
    """Only follow pagination URLs pinned to the StatusCake API origin.

    The session's default headers carry the account token, so an off-origin `links.next` (a
    tampered upstream response, or poisoned resume state read back from Redis) would send the
    credential to an attacker-controlled host. `allow_redirects=False` doesn't cover a direct
    off-origin request, so the URL itself must be validated before it's persisted or fetched.
    """
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "api.statuscake.com" and parts.path.startswith("/v1/")


def _get_session(api_key: str) -> requests.Session:
    # One session per sync so keep-alive is preserved across pages and the per-test fan-out.
    # `redact_values` masks the token from request telemetry/log samples, and
    # `allow_redirects=False` keeps a credentialed request pinned to the StatusCake host.
    return make_tracked_session(
        headers=_get_headers(api_key),
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _to_unix_timestamp(value: Any) -> Optional[int]:
    """Convert an incremental watermark (datetime/date/unix int/RFC3339 string) to UNIX seconds."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        parsed = _parse_rfc3339(value)
        return int(parsed.timestamp()) if parsed else None
    return None


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@retry(
    retry=retry_if_exception_type((StatusCakeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=90),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise StatusCakeRetryableError(f"StatusCake API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during the fan-out (a test deleted mid-sync) and handled by the caller.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"StatusCake API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_list_pages(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
    start_page: int = 1,
) -> Iterator[tuple[list[dict[str, Any]], int]]:
    """Yield (rows, page_number) for each non-empty page of a top-level list endpoint.

    Paginated list endpoints return a `metadata` object with `page`/`page_count`; we advance until
    `page_count` is exhausted. Some list endpoints (SSL, heartbeat, locations) return everything in
    one response with no metadata — for those the absence of `page_count` terminates after the
    first page, which also protects against endpoints that ignore the `page` param and would
    otherwise return the same full list forever.
    """
    page = start_page
    while True:
        url = _build_url(path, {"page": page, "limit": _PAGE_SIZE})
        data = _fetch_page(session, url, logger)
        rows = data.get("data", [])
        if not rows:
            return
        yield rows, page
        page_count = (data.get("metadata") or {}).get("page_count")
        if page_count is None or page >= page_count:
            return
        page += 1


def _list_test_ids(
    session: requests.Session, parent: StatusCakeEndpointConfig, logger: FilteringBoundLogger
) -> list[str]:
    """List every test id of the parent endpoint that history endpoints fan out over."""
    test_ids: list[str] = []
    for rows, _page in _iter_list_pages(session, parent.path, logger):
        for row in rows:
            # Direct access: the id drives the entire fan-out, so a test without one is a malformed
            # response we want to surface loudly rather than silently drop its history.
            test_ids.append(str(row["id"]))
    return test_ids


def _page_predates_watermark(
    rows: list[dict[str, Any]], timestamp_field: Optional[str], watermark: Optional[datetime]
) -> bool:
    """True when the oldest row of a (newest-first) page is older than the incremental watermark.

    Belt and braces for incremental pagination: even if the API ignores `after` (or drops it from
    the `links.next` cursor URL), we must not re-walk each test's full history on every sync.
    Unparseable timestamps never stop pagination — better to over-fetch than skip rows.
    """
    if watermark is None or timestamp_field is None or not rows:
        return False
    oldest = _parse_rfc3339(rows[-1].get(timestamp_field))
    return oldest is not None and oldest < watermark


def _iter_history_rows(
    session: requests.Session,
    config: StatusCakeEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StatusCakeResumeConfig],
    watermark_ts: Optional[int],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every parent test, yielding its (newest-first) history pages.

    History endpoints paginate with a cursor in the response's `links.next` and accept an `after`
    UNIX-timestamp lower bound, which carries the incremental watermark. The injected `test_id`
    makes the composite primary key unique table-wide.
    """
    assert config.fan_out_over is not None
    parent = STATUSCAKE_ENDPOINTS[config.fan_out_over]
    test_ids = _list_test_ids(session, parent, logger)

    params: dict[str, Any] = {"limit": _PAGE_SIZE}
    if watermark_ts is not None:
        # One second of overlap in case `after` is exclusive; merge dedupes on the primary key.
        params["after"] = watermark_ts - 1
    watermark = datetime.fromtimestamp(watermark_ts, tz=UTC) if watermark_ts is not None else None

    # Resolve the saved test-id bookmark to the slice of tests still to process. If the bookmarked
    # test no longer exists, start over from the first test — merge dedupes re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = test_ids
    resume_url: Optional[str] = None
    if resume is not None and resume.test_id is not None and resume.test_id in test_ids:
        remaining = test_ids[test_ids.index(resume.test_id) :]
        # An off-origin resume URL restarts the bookmarked test from its first page instead.
        resume_url = resume.next_url if _is_api_url(resume.next_url) else None
        logger.debug(f"StatusCake: resuming {config.name} from test_id={resume.test_id}, url={resume_url}")

    for index, test_id in enumerate(remaining):
        url = resume_url or _build_url(config.path.format(test_id=test_id), params)
        resume_url = None  # only the resumed-into test uses the saved URL; the rest start fresh

        try:
            while True:
                data = _fetch_page(session, url, logger)
                rows = data.get("data", [])
                if not rows:
                    break
                for row in rows:
                    row["test_id"] = test_id
                next_url = (data.get("links") or {}).get("next")
                if next_url and not _is_api_url(next_url):
                    logger.warning(f"StatusCake: ignoring off-origin next link for test {test_id}: {next_url}")
                    next_url = None
                yield rows
                # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
                # last page rather than skipping it — merge dedupes on the primary key.
                if next_url:
                    resumable_source_manager.save_state(StatusCakeResumeConfig(next_url=next_url, test_id=test_id))
                if not next_url or _page_predates_watermark(rows, config.timestamp_field, watermark):
                    break
                url = next_url
        except requests.HTTPError as exc:
            # A test deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — its history is genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"StatusCake: test {test_id} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next test so a crash between tests resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(StatusCakeResumeConfig(test_id=remaining[index + 1], next_url=None))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StatusCakeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = STATUSCAKE_ENDPOINTS[endpoint]
    session = _get_session(api_key)

    if config.fan_out_over is not None:
        watermark_ts = (
            _to_unix_timestamp(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value is not None
            else None
        )
        for rows in _iter_history_rows(session, config, logger, resumable_source_manager, watermark_ts):
            yield _scrub_rows(rows, config.scrub_fields)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_page = resume.page if resume is not None and resume.page is not None else 1
    if resume is not None:
        logger.debug(f"StatusCake: resuming {endpoint} from page {start_page}")
    for rows, page in _iter_list_pages(session, config.path, logger, start_page=start_page):
        yield _scrub_rows(rows, config.scrub_fields)
        resumable_source_manager.save_state(StatusCakeResumeConfig(page=page))


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Confirm the API token is genuine with one cheap probe against the uptime test listing."""
    url = _build_url("/uptime", {"limit": 1, "page": 1})
    try:
        response = _get_session(api_key).get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid StatusCake API token. Please check your token and try again."
    if response.status_code == 403:
        return False, "Your StatusCake API token does not have permission to list uptime checks."

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


def statuscake_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StatusCakeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = STATUSCAKE_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        return get_rows(
            api_key,
            endpoint,
            logger,
            resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_key,
        # History endpoints return rows newest-first, and the fan-out means a partial run's max
        # timestamp says nothing about tests it never reached — desc persists the incremental
        # watermark only at successful job end. Top-level lists are full refresh in stable page
        # order, so asc is correct there.
        sort_mode="desc" if config.fan_out_over is not None else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.timestamp_field else None,
        partition_format="month" if config.timestamp_field else None,
        partition_keys=[config.timestamp_field] if config.timestamp_field else None,
    )
