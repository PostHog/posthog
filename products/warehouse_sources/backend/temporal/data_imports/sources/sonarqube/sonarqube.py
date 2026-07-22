import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.settings import (
    ISSUES_MAX_RESULTS,
    PAGE_SIZE,
    SONARQUBE_ENDPOINTS,
    SonarqubeEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Hard cap on a single decoded response body. A user-configured server could serve an
# arbitrarily large or highly compressed page; the read timeout only bounds idle socket
# reads, not total size. Cap the decoded bytes so a misbehaving instance can't exhaust the
# worker's memory. A legitimate `ps=500` page is well under this.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

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


class SonarqubeRetryableError(Exception):
    pass


@dataclasses.dataclass
class SonarqubeResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: int | None = None
    # For the issues re-windowing: the `createdAfter` value of the window in progress. None for the
    # simple (non-windowed) endpoints and for an issues sync that hasn't re-windowed yet.
    created_after: str | None = None


def normalize_base_url(host: str) -> str:
    """Reduce user input to a validated SonarQube server base URL with no trailing slash or path.

    Accepts a bare host or a full URL. Bare hosts default to https; plaintext http:// is rejected
    because the token travels as a bearer header and must stay off the wire in the clear. Rejects
    anything without a hostname so the stored token can only ever be sent to the configured instance.
    """
    cleaned = host.strip()
    if not cleaned:
        raise ValueError("SonarQube server URL is required")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Invalid SonarQube server URL (must be https): {host}")
    # Keep scheme + netloc only; drop any path/query the user pasted so we control the API paths.
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname}{port}"


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


def _extract_paging(data: dict[str, Any]) -> tuple[int, int, int]:
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


@retry(
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
            logger.error(f"SonarQube API error: status={response.status_code}, body={body[:500]!r}, url={url}")
            response.raise_for_status()

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
        params = {**config.extra_params, "p": page, "ps": PAGE_SIZE}
        data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
        pages_fetched += 1
        items = data.get(config.response_key, [])
        page_index, page_size, total = _extract_paging(data)
        has_more = bool(items) and page_index * page_size < total

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
    """Page /api/issues/search ascending by creation date, re-windowing past the 10,000-result cap.

    Within one `createdAfter` window SonarQube only serves the first 10,000 results (p*ps<=10000).
    Once we exhaust that window we set `createdAfter` to the last issue's creationDate and start
    again. `createdAfter` is inclusive, so boundary issues re-appear across windows — merge dedupes
    them on the primary key. Sorting ascending keeps the incremental watermark advancing monotonically.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    created_after = resume.created_after if resume is not None and resume.created_after else initial_created_after
    page = resume.next_page if resume is not None and resume.next_page else 1
    if resume is not None and (resume.created_after or (resume.next_page and resume.next_page > 1)):
        logger.debug(f"SonarQube: resuming issues from createdAfter={created_after}, page={page}")

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
                batcher.batch(item)
                if batcher.should_yield():
                    yield batcher.get_table()
                    resumable_source_manager.save_state(
                        SonarqubeResumeConfig(next_page=page, created_after=created_after)
                    )

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
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session(redact_values=(token,), allow_redirects=False)

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
        sort_mode="asc",
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
