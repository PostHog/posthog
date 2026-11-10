import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.sdk.internals import Batcher
from products.warehouse_sources.sources.sonarqube.settings import (
    ISSUES_MAX_RESULTS,
    METRIC_KEYS_PER_REQUEST,
    PAGE_SIZE,
    SONARQUBE_ENDPOINTS,
    UNSUPPORTED_METRIC_TYPES,
    SonarqubeEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Hard cap on a single decoded response body. A user-configured server could serve an
# arbitrarily large or highly compressed page; the read timeout only bounds idle socket
# reads, not total size. Cap the decoded bytes so a misbehaving instance can't exhaust the
# worker's memory. A legitimate `ps=500` page is well under this.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

# Cap on the error text this source takes from a response body. That text reaches the job log and
# the `internal_error` field of the activity input that reports a failure, and a Temporal payload
# has a size limit, so an oversized detail would replace the status it is meant to explain. The
# sibling sources cap their error detail at the same length.
MAX_ERROR_DETAIL_CHARS = 500

# Wall-clock ceiling on reading a single response. The per-read timeout resets on every byte,
# so a server can drip data indefinitely and hold a shared worker; bound the whole transfer so
# a slow-drip host is cut off. Generous enough that a legitimate page never trips it.
MAX_TRANSFER_SECONDS = 300

# Pages we can request per issues window before p*ps breaches SonarQube's 10,000-result ceiling.
ISSUES_MAX_PAGES = ISSUES_MAX_RESULTS // PAGE_SIZE

# Absolute backstop on how many pages a single sync will fetch. SonarQube's list endpoints cap at
# p*ps<=10,000, and the issues sync re-windows past that, so a well-behaved server never comes near
# this. A user-controlled server can instead keep claiming more results (or advancing the issues
# window) indefinitely, looping forever and holding a shared import worker; cap the page count and
# fail non-retryably if it's ever breached. 50M rows is far beyond any real instance.
MAX_PAGES = 100_000

# Analysis dates are the scanner's start time, but an analysis only becomes visible once the server has
# processed it, which can be minutes later. Re-read a day before the watermark so a late analysis whose
# date sits just below it is not skipped; merge dedupes the overlap on the primary key.
HISTORY_LOOKBACK = timedelta(days=1)

# SonarQube Cloud is a separate product from the self-hosted Server this source targets, with its
# own source. Its list endpoints require an `organization` parameter we never send, so every page
# returns a 400. Both region hosts, and any subdomain of them.
SONARQUBE_CLOUD_HOSTNAMES = ("sonarcloud.io", "sonarqube.us")

SONARQUBE_CLOUD_ERROR = (
    "This URL points to SonarQube Cloud, which this source cannot read. "
    "Connect it with the Sonar Cloud source instead, which asks for your organization key."
)


# The message SonarQube answers with a 404 for an endpoint it does not serve, for example
# /api/project_pull_requests/list on Community Build.
UNKNOWN_URL_ERROR = "Unknown url"


class SonarqubeRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class SonarqubeResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: int | None = None
    # For the issues re-windowing: the `createdAfter` value of the window in progress. None for the
    # simple (non-windowed) endpoints and for an issues sync that hasn't re-windowed yet.
    created_after: str | None = None
    # For the per-project fan-out endpoints: the project and metric chunk the next page belongs to.
    project_key: str | None = None
    metric_chunk: int | None = None
    # For the issue changelog: the last issue on `next_page` whose changelog was read.
    issue_key: str | None = None


def normalize_base_url(host: str) -> str:
    """Reduce user input to a validated SonarQube server base URL with no trailing slash or path.

    Accepts a bare host or a full URL. Bare hosts default to https; plaintext http:// is rejected
    because the token travels as a bearer header and must stay off the wire in the clear. Rejects
    anything without a hostname so the stored token can only ever be sent to the configured instance.
    Rejects SonarQube Cloud, which this source cannot sync.
    """
    cleaned = host.strip()
    if not cleaned:
        raise ValueError("SonarQube server URL is required")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    # `parsed.hostname` lowercases the host but keeps a terminal DNS dot, and `sonarcloud.io.`
    # reaches the same server as `sonarcloud.io`. Strip the dot so the cloud check below cannot be
    # sidestepped, and so the host we validate is the host we request.
    hostname = (parsed.hostname or "").rstrip(".")
    if parsed.scheme != "https" or not hostname:
        raise ValueError(f"Invalid SonarQube server URL (must be https): {host}")
    if any(hostname == name or hostname.endswith(f".{name}") for name in SONARQUBE_CLOUD_HOSTNAMES):
        # Cloud accepts the credential probe (/api/authentication/validate answers 200 there), so
        # without this check setup succeeds and every list endpoint then fails with a 400.
        raise ValueError(SONARQUBE_CLOUD_ERROR)
    # Keep scheme + netloc only; drop any path/query the user pasted so we control the API paths.
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{hostname}{port}"


def hostname_of(host: str) -> str:
    return urlparse(normalize_base_url(host)).hostname or ""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _format_created_after(value: Any) -> str:
    """Format an incremental cursor as the datetime string SonarQube's `createdAfter` accepts.

    SonarQube expects `yyyy-MM-ddTHH:mm:ss+hhmm`; a naive datetime is assumed UTC.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S%z")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S%z")
    return str(value)


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def _extract_paging(
    data: dict[str, Any],
) -> tuple[int, int, int]:  # nosemgrep: tuple-return-prefer-dataclass -- pre-existing, file moved
    """Return (pageIndex, pageSize, total) from either SonarQube paging shape.

    Most endpoints wrap it in a `paging` object; /api/metrics/search returns `p`, `ps`, `total`
    at the top level instead.
    """
    paging = data.get("paging")
    if isinstance(paging, dict):
        return (
            int(paging.get("pageIndex", 1)),
            int(paging.get("pageSize", PAGE_SIZE)),
            int(paging.get("total", 0)),
        )
    return (
        int(data.get("p", 1)),
        int(data.get("ps", PAGE_SIZE)),
        int(data.get("total", 0)),
    )


def _error_detail(body: bytes) -> str:
    """Return SonarQube's own explanation of a failed request.

    Error responses carry ``{"errors": [{"msg": "..."}]}``. Fall back to the raw body so an
    unexpected shape still tells the user something. The result is capped at
    ``MAX_ERROR_DETAIL_CHARS`` because the server chooses its length.
    """
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        payload = None
    # A misconfigured host, or a gateway in front of the instance, can put any JSON value under
    # `errors`, so confirm it is a list before iterating it. A non-list would raise a TypeError
    # here, which would replace the status and body this function exists to report.
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list):
        messages = [str(error["msg"]) for error in errors if isinstance(error, dict) and error.get("msg")]
        if messages:
            return "; ".join(messages)[:MAX_ERROR_DETAIL_CHARS]
    # Decode only the bytes the cap can use. The body is already in memory and can reach
    # MAX_RESPONSE_BYTES, so decoding all of it would spend that much again for a string we then
    # throw away. UTF-8 uses at most 4 bytes per character, so this slice always covers the cap.
    text = body[: MAX_ERROR_DETAIL_CHARS * 4].decode("utf-8", "replace").strip()
    return text[:MAX_ERROR_DETAIL_CHARS] if text else "no error message"


def _read_bounded(response: requests.Response) -> bytes:
    """Read a streamed response body into memory under a byte cap and a wall-clock deadline.

    `iter_content` yields content-decoded chunks, so the running total also caps decompressed
    size — a small gzip bomb can't blow past the limit. A monotonic deadline checked between
    chunks bounds the whole transfer so a server that drips data can't hold the worker
    indefinitely. Raises a non-retryable ``ValueError`` when either bound is exceeded. This mirrors
    the `_read_capped_body` convention shared by the langfuse/instana/formbricks/qualys_vmdr
    sources; the per-read idle timeout and the platform's 2-minute activity heartbeat are the
    backstops for a read blocked mid-chunk.
    """
    started = time.monotonic()
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"SonarQube response exceeded the {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB limit; "
                "check the configured server URL."
            )
        if time.monotonic() - started > MAX_TRANSFER_SECONDS:
            raise ValueError(
                f"SonarQube response exceeded the {MAX_TRANSFER_SECONDS}s transfer limit; "
                "check the configured server URL."
            )
        chunks.append(chunk)
    return b"".join(chunks)


@retry_with_deadline(
    retry=retry_if_exception_type((SonarqubeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    # Streamed so the body is read under a byte cap rather than buffered whole by `requests`.
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)
    try:
        # Rate limits are governed by the customer's own instance capacity rather than a vendor quota;
        # back off and retry on 429 and transient 5xx rather than failing the sync.
        if response.status_code == 429 or response.status_code >= 500:
            raise SonarqubeRetryableError(f"SonarQube API error (retryable): status={response.status_code}, url={url}")

        # Redirects are disabled at the session level as an SSRF boundary; a 3xx means the configured
        # server is redirecting elsewhere, which we treat as a configuration error rather than follow.
        if 300 <= response.status_code < 400:
            raise ValueError(
                f"SonarQube server returned an unexpected redirect (status={response.status_code}); "
                "check the configured server URL."
            )

        body = _read_bounded(response)

        if not response.ok:
            detail = _error_detail(body)
            logger.error(f"SonarQube API error: status={response.status_code}, detail={detail}, url={url}")
            # Built by hand rather than with `raise_for_status()`: SonarQube sends an empty HTTP
            # reason phrase, so the library message reads "400 Client Error:  for url: ..." and
            # drops the server's own explanation of what is wrong.
            raise requests.HTTPError(f"{response.status_code} Client Error: {detail} for url: {url}", response=response)

        return json.loads(body or b"null")
    finally:
        response.close()


def _iter_simple(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    config: SonarqubeEndpointConfig,
) -> Iterator[Any]:
    """Page through a list endpoint with SonarQube's 1-based `p`/`ps` pagination (full refresh)."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None and resume.next_page else 1
    if page > 1:
        logger.debug(f"SonarQube: resuming {config.name} from page {page}")

    pages_fetched = 0
    while True:
        if pages_fetched >= MAX_PAGES:
            # A well-behaved server drops has_more long before this; a server that keeps claiming
            # more results would loop forever and hold the worker. Fail non-retryably instead.
            raise ValueError(
                f"SonarQube {config.name} exceeded the {MAX_PAGES}-page safety cap; the server keeps "
                "reporting more results. Check the configured server URL."
            )
        params = {**config.extra_params, "p": page, "ps": PAGE_SIZE} if config.paginated else config.extra_params
        data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
        pages_fetched += 1
        items = data.get(config.response_key, [])
        page_index, page_size, total = _extract_paging(data)
        has_more = config.paginated and bool(items) and page_index * page_size < total

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
                # merge dedupes on the primary key.
                if has_more:
                    resumable_source_manager.save_state(SonarqubeResumeConfig(next_page=page + 1))

        if not has_more:
            break
        page += 1


@dataclasses.dataclass(frozen=True)
class _IssuePage:
    items: list[dict[str, Any]]
    # The `createdAfter` window and page that produced these items, for resume state.
    created_after: str | None
    page: int


def _iter_issue_pages(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: SonarqubeEndpointConfig,
    created_after: str | None,
    page: int,
) -> Iterator[_IssuePage]:
    """Page /api/issues/search ascending by creation date, re-windowing past the 10,000-result cap.

    Within one `createdAfter` window SonarQube only serves the first 10,000 results (p*ps<=10000).
    Once we exhaust that window we set `createdAfter` to the last issue's creationDate and start
    again. `createdAfter` is inclusive, so boundary issues re-appear across windows — merge dedupes
    them on the primary key. Sorting ascending keeps the incremental watermark advancing monotonically.
    """
    pages_fetched = 0
    while True:
        last_creation_date: str | None = None
        window_exhausted = False

        while True:
            if pages_fetched >= MAX_PAGES:
                # Each window is bounded, but a server that keeps advancing the window with full
                # pages would spawn windows forever and hold the worker. Fail non-retryably instead.
                raise ValueError(
                    f"SonarQube issues exceeded the {MAX_PAGES}-page safety cap; the server keeps "
                    "advancing the window with more results. Check the configured server URL."
                )
            params: dict[str, Any] = {"s": "CREATION_DATE", "asc": "true", "p": page, "ps": PAGE_SIZE}
            if created_after:
                params["createdAfter"] = created_after
            data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
            pages_fetched += 1
            items = data.get(config.response_key, [])
            page_index, page_size, total = _extract_paging(data)

            for item in items:
                creation_date = item.get("creationDate")
                if creation_date:
                    last_creation_date = creation_date
            yield _IssuePage(items=items, created_after=created_after, page=page)

            if not items or page_index * page_size >= total:
                # Fetched every result the server will return for this window and there is no
                # further window — the whole endpoint is drained.
                return
            if page + 1 > ISSUES_MAX_PAGES:
                # The next page would breach the 10,000-result ceiling; re-window instead.
                window_exhausted = True
                break
            page += 1

        if not window_exhausted:
            return
        # A window with >10,000 results whose newest row shares createdAfter can't advance; stop
        # rather than loop forever (merge already has those rows).
        if not last_creation_date or last_creation_date == created_after:
            logger.warning(
                f"SonarQube: cannot advance issues window past createdAfter={created_after}; "
                "more than 10,000 issues share this timestamp. Stopping to avoid an infinite loop."
            )
            return
        created_after = last_creation_date
        page = 1


def _iter_windowed_issues(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    config: SonarqubeEndpointConfig,
    initial_created_after: str | None,
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    created_after = resume.created_after if resume is not None and resume.created_after else initial_created_after
    page = resume.next_page if resume is not None and resume.next_page else 1
    if resume is not None and (resume.created_after or (resume.next_page and resume.next_page > 1)):
        logger.debug(f"SonarQube: resuming issues from createdAfter={created_after}, page={page}")

    for issue_page in _iter_issue_pages(session, base_url, headers, logger, config, created_after, page):
        for item in issue_page.items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                resumable_source_manager.save_state(
                    SonarqubeResumeConfig(next_page=issue_page.page, created_after=issue_page.created_after)
                )


def _iter_issue_changelog(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    config: SonarqubeEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Read the changelog of every issue, walking the issues the same way the issues table does.

    The state staged before each issue's rows names the issues page and that issue, so a resumed
    run reads the page again and starts after the last issue written.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    created_after = resume.created_after if resume is not None else None
    page = resume.next_page if resume is not None and resume.next_page else 1
    skip_through = resume.issue_key if resume is not None else None
    if skip_through:
        logger.debug(f"SonarQube: resuming {config.name} after issue {skip_through}, page={page}")

    issues = SONARQUBE_ENDPOINTS["issues"]
    for issue_page in _iter_issue_pages(session, base_url, headers, logger, issues, created_after, page):
        # Nothing is held yet, so the run can hand off before the page's changelog requests.
        resumable_source_manager.safe_point()
        items = [item for item in issue_page.items if isinstance(item, dict) and item.get("key")]
        if skip_through is not None:
            keys = [item["key"] for item in items]
            # An issue deleted since the last attempt cannot be located, so its page is read again.
            if skip_through in keys:
                items = items[keys.index(skip_through) + 1 :]
            skip_through = None

        for issue in items:
            issue_key = issue["key"]
            try:
                data = _fetch_page(session, _build_url(base_url, config.path, {"issue": issue_key}), headers, logger)
            except requests.HTTPError as error:
                # The issue was deleted after we listed it.
                if error.response is None or error.response.status_code != 404:
                    raise
                logger.info(f"SonarQube: issue {issue_key} not found for {config.name}; skipping it")
                data = {}
            rows = [
                {"issue": issue_key, "project": issue.get("project"), "changeIndex": index, **change}
                for index, change in enumerate(data.get(config.response_key) or [])
                if isinstance(change, dict)
            ]
            resumable_source_manager.save_state(
                SonarqubeResumeConfig(
                    next_page=issue_page.page, created_after=issue_page.created_after, issue_key=issue_key
                )
            )
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()


def _iter_list(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    config: SonarqubeEndpointConfig,
) -> Iterator[dict[str, Any]]:
    """Read every item of a paged list endpoint that the fan-out needs before its first row."""
    page = 1
    while True:
        if page > MAX_PAGES:
            raise ValueError(
                f"SonarQube {config.name} exceeded the {MAX_PAGES}-page safety cap; the server keeps "
                "reporting more results. Check the configured server URL."
            )
        params = {**config.extra_params, "p": page, "ps": PAGE_SIZE}
        data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
        # Nothing is yielded or held yet, so the run can hand off between these requests.
        resumable_source_manager.safe_point()
        items = data.get(config.response_key) or []
        yield from (item for item in items if isinstance(item, dict))
        page_index, page_size, total = _extract_paging(data)
        if not items or page_index * page_size >= total:
            return
        page += 1


def _measure_rows(project_key: str, component: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "project": project_key,
            "component": component.get("key"),
            "componentName": component.get("name"),
            "qualifier": component.get("qualifier"),
            "path": component.get("path"),
            "language": component.get("language"),
            "metric": measure.get("metric"),
            "value": measure.get("value"),
            "bestValue": measure.get("bestValue"),
            # New-code values come back under `period` instead of `value`.
            "periodValue": (measure.get("period") or {}).get("value"),
        }
        for measure in component.get("measures") or []
        if isinstance(measure, dict)
    ]


def _fanout_params(
    config: SonarqubeEndpointConfig, project_key: str, metric_keys: list[str], page: int, history_from: str | None
) -> dict[str, Any]:
    assert config.fanout is not None
    params: dict[str, Any] = {**config.extra_params}
    params.update(dict.fromkeys(config.fanout.project_params, project_key))
    if config.fanout.kind == "component_measures":
        params["metricKeys"] = ",".join(metric_keys)
    elif config.fanout.kind == "measures_history":
        params["metrics"] = ",".join(metric_keys)
    if history_from and config.supports_incremental:
        params["from"] = history_from
    if config.paginated:
        params.update({"p": page, "ps": config.fanout.page_size})
    return params


@dataclasses.dataclass(frozen=True)
class _FanoutPage:
    rows: list[dict[str, Any]]
    has_more: bool


def _fanout_page(config: SonarqubeEndpointConfig, project_key: str, data: dict[str, Any], page: int) -> _FanoutPage:
    """Return the rows of one fan-out page and whether the server reports another page."""
    assert config.fanout is not None
    kind = config.fanout.kind
    if kind == "quality_gate_status":
        status = data.get(config.response_key)
        return _FanoutPage(
            rows=[{"projectKey": project_key, **status}] if isinstance(status, dict) else [], has_more=False
        )

    items = [item for item in data.get(config.response_key) or [] if isinstance(item, dict)]
    rows: list[dict[str, Any]]
    if kind == "hotspots":
        rows = items
    elif kind == "project_rows":
        rows = [{"project": project_key, **item} for item in items]
    elif kind == "component_measures":
        # The base component (the project itself) repeats on every page; take it from the first.
        base = data.get("baseComponent")
        rows = _measure_rows(project_key, base) if page == 1 and isinstance(base, dict) else []
        for component in items:
            rows.extend(_measure_rows(project_key, component))
    else:
        rows = [
            {"project": project_key, "metric": measure.get("metric"), "date": point["date"], "value": point["value"]}
            for measure in items
            for point in measure.get("history") or []
            # A point with no value means the metric was not computed in that analysis.
            if isinstance(point, dict) and point.get("date") and point.get("value") is not None
        ]
    page_index, page_size, total = _extract_paging(data)
    return _FanoutPage(rows=rows, has_more=bool(items) and page_index * page_size < total)


def _history_from(value: Any) -> str:
    if isinstance(value, datetime | date):
        value = value - HISTORY_LOOKBACK
    return _format_created_after(value)


def _iter_project_fanout(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    config: SonarqubeEndpointConfig,
    history_from: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Run an endpoint once per project, and once per metric chunk for the measures endpoints.

    Each page is yielded as it arrives, with the position of the next page staged before it, so a
    resumed run starts at the page after the last one written.
    """
    fanout = config.fanout
    assert fanout is not None
    projects = SONARQUBE_ENDPOINTS["projects"]
    project_keys = [
        item["key"]
        for item in _iter_list(session, base_url, headers, logger, resumable_source_manager, projects)
        if item.get("key")
    ]
    metric_chunks: list[list[str]] = [[]]
    if fanout.kind in ("component_measures", "measures_history"):
        metric_keys = [
            item["key"]
            for item in _iter_list(
                session, base_url, headers, logger, resumable_source_manager, SONARQUBE_ENDPOINTS["metrics"]
            )
            if item.get("key") and item.get("type") not in UNSUPPORTED_METRIC_TYPES
        ]
        metric_chunks = [
            metric_keys[i : i + METRIC_KEYS_PER_REQUEST] for i in range(0, len(metric_keys), METRIC_KEYS_PER_REQUEST)
        ]
    if not project_keys or not metric_chunks:
        return

    positions = [
        (project_index, chunk_index)
        for project_index in range(len(project_keys))
        for chunk_index in range(len(metric_chunks))
    ]
    start, page = 0, 1
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.project_key:
        if resume.project_key in project_keys:
            start = positions.index(
                (project_keys.index(resume.project_key), min(resume.metric_chunk or 0, len(metric_chunks) - 1))
            )
            page = resume.next_page or 1
            logger.debug(f"SonarQube: resuming {config.name} from project={resume.project_key}, page={page}")
        else:
            logger.warning(
                f"SonarQube: project {resume.project_key} to resume {config.name} from is gone; starting over"
            )

    index = start
    while index < len(positions):
        project_index, chunk_index = positions[index]
        project_key = project_keys[project_index]
        pages_fetched = 0
        while True:
            if pages_fetched >= MAX_PAGES:
                raise ValueError(
                    f"SonarQube {config.name} exceeded the {MAX_PAGES}-page safety cap for project "
                    f"{project_key}; the server keeps reporting more results. Check the configured server URL."
                )
            params = _fanout_params(config, project_key, metric_chunks[chunk_index], page, history_from)
            try:
                data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
            except requests.HTTPError as error:
                if error.response is None or error.response.status_code != 404:
                    raise
                if UNKNOWN_URL_ERROR in str(error):
                    # This edition of SonarQube does not serve the endpoint, for any project.
                    logger.warning(f"SonarQube: this server does not serve {config.path}; {config.name} stays empty")
                    return
                # The project was deleted after we listed it.
                logger.info(f"SonarQube: project {project_key} not found for {config.name}; skipping it")
                fanout_page = _FanoutPage(rows=[], has_more=False)
                index = (project_index + 1) * len(metric_chunks) - 1
            else:
                fanout_page = _fanout_page(config, project_key, data, page)
            rows, has_more = fanout_page.rows, fanout_page.has_more
            pages_fetched += 1
            if has_more and fanout.max_pages is not None and page >= fanout.max_pages:
                logger.warning(
                    f"SonarQube: {config.name} for project {project_key} has more than "
                    f"{fanout.max_pages * fanout.page_size} results; the server serves no more than that"
                )
                has_more = False

            if has_more:
                page += 1
            else:
                index += 1
                page = 1
            if index < len(positions):
                next_project_index, next_chunk_index = positions[index]
                resumable_source_manager.save_state(
                    SonarqubeResumeConfig(
                        project_key=project_keys[next_project_index], metric_chunk=next_chunk_index, next_page=page
                    )
                )
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()
            if not has_more:
                break


def get_rows(
    host: str,
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = SONARQUBE_ENDPOINTS[endpoint]
    base_url = normalize_base_url(host)
    headers = _headers(token)
    session = make_tracked_session(redact_values=(token,), allow_redirects=False)

    if config.per_issue:
        yield from _iter_issue_changelog(session, base_url, headers, logger, resumable_source_manager, config)
        return

    if config.fanout is not None:
        history_from = (
            _history_from(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )
        yield from _iter_project_fanout(
            session, base_url, headers, logger, resumable_source_manager, config, history_from
        )
        return

    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    if config.windowed_incremental:
        initial_created_after = (
            _format_created_after(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )
        yield from _iter_windowed_issues(
            session, base_url, headers, logger, batcher, resumable_source_manager, config, initial_created_after
        )
    else:
        yield from _iter_simple(session, base_url, headers, logger, batcher, resumable_source_manager, config)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def sonarqube_source(
    host: str,
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SONARQUBE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            token=token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Issues are fetched ascending by creation date, so the watermark advances safely per batch.
        # The measures history and project analyses are ordered per project only, so they are not one
        # ordered series.
        sort_mode="asc" if config.windowed_incremental else None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(host: str, token: str) -> tuple[bool, int | None]:
    """Probe /api/authentication/validate to confirm the token is genuine.

    Returns ``(ok, status_code)``. This endpoint needs no project permission, so a token that can
    only read some projects still validates at source creation. ``status_code`` is ``None`` on a
    transport error; raises ``ValueError`` if the server URL is malformed.
    """
    url = _build_url(normalize_base_url(host), "/api/authentication/validate", {})
    try:
        response = make_tracked_session(redact_values=(token,), allow_redirects=False).get(
            url, headers=_headers(token), timeout=10, stream=True
        )
    except Exception:
        return False, None
    try:
        if response.status_code != 200:
            return False, response.status_code
        try:
            payload = json.loads(_read_bounded(response) or b"null")
            return bool(payload.get("valid")), response.status_code
        except Exception:
            return False, response.status_code
    finally:
        response.close()
