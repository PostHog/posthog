import re
import json
import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.settings import (
    DEFAULT_BASE_URL,
    LANGSMITH_ENDPOINTS,
    RUNS_SELECT_FIELDS,
    LangSmithEndpointConfig,
)

# Returned when the resolved host resolves to a private/internal address on cloud (SSRF guard).
HOST_NOT_ALLOWED_ERROR = "LangSmith host is not allowed"

# Returned when a cloud connection would send the API key over plaintext HTTP.
INSECURE_SCHEME_ERROR = "LangSmith host must use https"

# Raised (and registered non-retryable) when the host loops the runs cursor. A host that returns a
# cursor we've already paged is stuck or hostile; retrying re-hits the same cursor, so fail for good.
REPEATED_CURSOR_ERROR = "LangSmith returned a repeated pagination cursor"

# Cap the decoded body of any single LangSmith response. `host` is user-controlled, so a hostile
# server could otherwise stream an unbounded body and exhaust a shared import worker's memory. Set
# well above any realistic page (runs pages carry full LLM inputs/outputs) so it only trips on a
# genuinely abnormal response.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024

# How much of an error-response body to keep for the log line (bounded for the same reason).
MAX_ERROR_BODY_BYTES = 8 * 1024

# Encoded bytes read per streamed chunk while enforcing MAX_RESPONSE_BYTES. Kept small so a single
# decompressed chunk can't inflate far past the cap before we notice — a hostile host could otherwise
# hand back a small gzip bomb that a one-shot decoded read would expand into memory all at once.
READ_CHUNK_BYTES = 64 * 1024

# A real pagination cursor is a short opaque token. A host handing back anything larger is broken or
# hostile — reject it rather than echo it back in the next request body or hold it in memory.
MAX_CURSOR_BYTES = 8 * 1024

# Bound how many pages one activity attempt walks. A hostile host can otherwise return a full page
# with a fresh cursor/offset forever and hold a worker until the week-long activity timeout. On the
# cap we persist the resume checkpoint and raise, so the attempt ends but a legitimate oversized
# import continues from the checkpoint on the next attempt. Generous: the runs rate limits alone
# make hitting this in one attempt take days.
MAX_PAGES_PER_RUN = 50_000

# Cap the total bytes of session ids accumulated while scoping the runs query. `host` is
# user-controlled and returns arbitrary `id` strings on every project page, so without a cumulative
# cap a host could return unboundedly many (or oversized) ids across thousands of pages — well
# before MAX_PAGES_PER_RUN trips — and exhaust a shared import worker's memory. ~58k real UUIDs'
# worth, far beyond any legitimate workspace's tracing-project count.
MAX_SESSION_IDS_BYTES = 2 * 1024 * 1024

# Same cumulative-memory guard as MAX_SESSION_IDS_BYTES, applied to the dataset ids collected to
# scope the examples query. A user-controlled host could otherwise stream unbounded dataset ids.
MAX_DATASET_IDS_BYTES = 2 * 1024 * 1024


class LangSmithRetryableError(Exception):
    pass


class LangSmithHostNotAllowedError(Exception):
    """The resolved host is blocked (SSRF guard) or tried to redirect the authenticated request."""

    pass


class LangSmithResponseTooLargeError(Exception):
    """The host returned a body larger than `MAX_RESPONSE_BYTES` — refused before buffering it all."""

    pass


class LangSmithPageLimitError(Exception):
    """One activity attempt walked `MAX_PAGES_PER_RUN` pages. Retryable: resume from the checkpoint."""

    pass


class LangSmithRepeatedCursorError(Exception):
    """The host looped the runs cursor. Non-retryable (see REPEATED_CURSOR_ERROR) — retrying re-loops."""

    pass


def _read_capped_body(response: requests.Response, cap: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read at most `cap` decoded bytes from a streamed response, refusing an oversized body.

    Requests are made with `stream=True` so the body isn't materialised until this read. We stream the
    decompressed body in small chunks and stop the moment the running decoded total exceeds the cap.
    Reading the whole body in one shot with `decode_content=True` only bounds the encoded bytes: a
    hostile host could return a small gzip bomb that inflates past the cap in memory before we ever
    check its size. Streaming keeps the peak bounded to roughly one chunk's worth of inflation.
    """
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=READ_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > cap:
            raise LangSmithResponseTooLargeError(f"LangSmith API returned an oversized response (> {cap} bytes)")
    return bytes(buffer)


@dataclasses.dataclass(frozen=False)  # mutability is unused (always constructed fresh); explicit per house convention
class LangSmithResumeConfig:
    # runs/query body cursor for the page to fetch next; None for offset-paginated endpoints.
    cursor: str | None = None
    # Offset to resume paginating from on offset/limit endpoints; None for the runs endpoint.
    offset: int | None = None
    # The server-side time-window lower bound the interrupted run started with, pinned so a
    # resumed run keeps paging the same window (a recomputed bound would shift what each
    # cursor/offset points at).
    window_start: str | None = None
    # Dataset being paged when an examples run was interrupted; examples are fetched per dataset,
    # so the resume needs both which dataset and the offset within it. None for every other endpoint.
    dataset_id: str | None = None


def normalize_base_url(raw: str) -> str:
    """Reduce a host or URL to a clean `scheme://host[:port]` origin.

    Any path, query, or fragment is dropped so a crafted host value can't extend or retarget the
    fixed LangSmith API paths. A bare host gains an https scheme; an explicit http/https scheme is
    preserved (self-hosted instances may run plaintext on a private network)."""
    raw = raw.strip()
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    scheme = scheme if scheme in ("http", "https") else "https"
    # Rebuild the authority from the parsed hostname/port only — never the raw `netloc`. Keeping
    # `netloc` verbatim lets a value like `https://127.0.0.1\@evil.com` pass the hostname allowlist as
    # `evil.com` (what `urlparse` sees) while `requests` connects to `127.0.0.1` (what its WHATWG-style
    # parser sees): a parser-mismatch SSRF. It also drops any `user:pass@` userinfo, which we never use
    # (auth is the X-API-Key header). Rebuilding guarantees the host we validate is the host we hit.
    host = parsed.hostname or ""
    if ":" in host:  # IPv6 literal — hostname strips the brackets that the URL form needs back
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    authority = host if port is None else f"{host}:{port}"
    return f"{scheme}://{authority}"


def _host_from_url(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def _is_scheme_safe(base_url: str) -> tuple[bool, str | None]:
    """On cloud, refuse to send the API key over plaintext HTTP.

    Self-hosted PostHog may reach a private LangSmith instance over http on a trusted network, so —
    as with the SSRF host check — this is only enforced on cloud, where a plaintext origin would
    leak the key in transit."""
    if urlparse(base_url).scheme == "https" or not is_cloud():
        return True, None
    return False, INSECURE_SCHEME_ERROR


def _check_host(base_url: str, team_id: int) -> None:
    """SSRF/plaintext guard for the user-controlled host the API key is sent to. Raises on failure."""
    host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
    if not host_ok:
        raise LangSmithHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    scheme_ok, scheme_err = _is_scheme_safe(base_url)
    if not scheme_ok:
        raise LangSmithHostNotAllowedError(scheme_err or INSECURE_SCHEME_ERROR)


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an ISO 8601 UTC timestamp with a `Z` suffix."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return None


def _resolve_window_start(
    config: LangSmithEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> datetime | None:
    """Compute the server-side time-window lower bound to send.

    - Incremental run with a watermark: the watermark, shifted back by the lookback overlap and
      capped at now (a future-dated cursor would make the API return nothing).
    - First incremental run (no watermark): floored to `default_lookback_days` so the backfill is
      bounded instead of crawling the whole retention window against the tight run-query limits.
    - Full refresh: no bound — the endpoint's retention window bounds real history anyway.
    """
    if config.window_param is None or not should_use_incremental_field:
        return None

    now = datetime.now(UTC)

    if db_incremental_field_last_value:
        watermark = _to_datetime(db_incremental_field_last_value) or now
        watermark = min(watermark, now)
        if config.incremental_lookback:
            watermark = watermark - config.incremental_lookback
        return watermark

    if config.default_lookback_days:
        return now - timedelta(days=config.default_lookback_days)

    return None


def validate_credentials(api_key: str, host: str | None, team_id: int | None = None) -> tuple[bool, str | None]:
    """Probe the key by listing one tracing project — the cheapest workspace-scoped read with no
    required filters. A 200 confirms the key is genuine."""
    base_url = normalize_base_url(host or DEFAULT_BASE_URL)

    # The host is user-controlled and the API key is sent to it, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        try:
            _check_host(base_url, team_id)
        except LangSmithHostNotAllowedError as e:
            return False, str(e)

    url = f"{base_url}/api/v1/sessions?{urlencode({'limit': 1})}"
    try:
        # Redact the key, never follow a redirect off the validated host, and keep the response out
        # of HTTP sample capture — LangSmith payloads carry LLM prompts/outputs that can embed
        # secrets or personal data the name-based scrubber won't recognize. `stream=True` so a
        # hostile host can't make us buffer an unbounded body: we only read the status code, then
        # close the connection without ever pulling the body.
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False).get(
            url, headers=_get_headers(api_key), timeout=10, stream=True
        )
        try:
            status_code = response.status_code
        finally:
            response.close()
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if status_code == 200:
        return True, None
    if status_code == 401:
        return False, "Invalid or revoked LangSmith API key"
    if status_code == 403:
        return False, "This LangSmith API key does not have access to the workspace"
    if status_code == 404:
        return False, "LangSmith API not found at this host. Check the host field."
    return False, f"LangSmith API returned status {status_code}"


@retry(
    retry=retry_if_exception_type(
        (
            LangSmithRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """GET the URL, or POST `json_body` to it when given (the runs/query endpoint).

    `stream=True` so the body isn't buffered until we read it under `MAX_RESPONSE_BYTES` — `host` is
    user-controlled, so an unbounded body could otherwise exhaust the worker's memory.
    """
    if json_body is not None:
        response = session.post(url, headers=headers, json=json_body, timeout=60, stream=True)
    else:
        response = session.get(url, headers=headers, timeout=60, stream=True)

    with response:
        # 429 and transient 5xx are retryable (runs/query rate limits are tight: 10 req/10s on
        # windows up to 7 days, 3 req/10s beyond); auth/permission errors below are not.
        if response.status_code == 429 or response.status_code >= 500:
            raise LangSmithRetryableError(f"LangSmith API error (retryable): status={response.status_code}, url={url}")

        # Redirects are disabled as an SSRF boundary; a 3xx means the host tried to bounce the
        # authenticated request elsewhere, so fail instead of parsing (or following) it.
        if 300 <= response.status_code < 400:
            raise LangSmithHostNotAllowedError(
                f"LangSmith API returned an unexpected redirect: status={response.status_code}, url={url}"
            )

        if not response.ok:
            # Truncate (don't cap-and-raise) so a large error body still surfaces the real HTTP error.
            body = response.raw.read(MAX_ERROR_BODY_BYTES, decode_content=True).decode("utf-8", errors="replace")
            logger.error(f"LangSmith API error: status={response.status_code}, body={body}, url={url}")
            response.raise_for_status()

        raw = _read_capped_body(response)
        return json.loads(raw) if raw else None


def _list_session_ids(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    """Collect every tracing-project (session) id in the workspace.

    runs/query rejects a request that doesn't scope to at least one of session/id/parent_run/
    trace/reference_example; this sync pulls runs across every project, so it scopes by every
    session id in the workspace instead of narrowing to one.
    """
    config = LANGSMITH_ENDPOINTS["projects"]
    ids: list[str] = []
    ids_bytes = 0
    offset = 0
    pages = 0
    while True:
        url = f"{base_url}{config.path}?{urlencode({'limit': config.page_size, 'offset': offset})}"
        data = _fetch_page(session, url, headers, logger)
        rows = data if isinstance(data, list) else []
        if not rows:
            break
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                continue
            ids.append(row_id)
            ids_bytes += len(row_id.encode())
            if ids_bytes > MAX_SESSION_IDS_BYTES:
                raise LangSmithResponseTooLargeError(
                    f"LangSmith returned an oversized set of tracing-project ids "
                    f"(> {MAX_SESSION_IDS_BYTES} bytes) while scoping the runs query"
                )
        if len(rows) < config.page_size:
            break
        offset += config.page_size
        # Same hostile-host guard as the other paginators: a host returning a full page forever
        # must not hold the worker until the activity timeout.
        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            raise LangSmithPageLimitError(
                f"LangSmith session listing hit the {MAX_PAGES_PER_RUN}-page limit while scoping the runs query"
            )
    return ids


def _list_dataset_ids(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    """Collect every dataset id in the workspace.

    GET /examples requires a `dataset` filter (a 400 otherwise); this sync pulls examples across
    every dataset, so it lists dataset ids and pages each dataset's examples in turn.
    """
    config = LANGSMITH_ENDPOINTS["datasets"]
    ids: list[str] = []
    ids_bytes = 0
    offset = 0
    pages = 0
    while True:
        url = f"{base_url}{config.path}?{urlencode({'limit': config.page_size, 'offset': offset})}"
        data = _fetch_page(session, url, headers, logger)
        rows = data if isinstance(data, list) else []
        if not rows:
            break
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                continue
            ids.append(row_id)
            ids_bytes += len(row_id.encode())
            if ids_bytes > MAX_DATASET_IDS_BYTES:
                raise LangSmithResponseTooLargeError(
                    f"LangSmith returned an oversized set of dataset ids "
                    f"(> {MAX_DATASET_IDS_BYTES} bytes) while scoping the examples query"
                )
        if len(rows) < config.page_size:
            break
        offset += config.page_size
        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            raise LangSmithPageLimitError(
                f"LangSmith dataset listing hit the {MAX_PAGES_PER_RUN}-page limit while scoping the examples query"
            )
    return ids


def _get_runs_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    config: LangSmithEndpointConfig,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    """Page through POST /runs/query with the body cursor.

    The full body (including the start_time window) is re-sent with every cursor request, so every
    page stays bounded by the watermark — incremental syncs can't walk back through history."""
    url = f"{base_url}{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        cursor = resume.cursor
        window_start = resume.window_start
        logger.debug(f"LangSmith: resuming runs from cursor={cursor}")
    else:
        cursor = None
        start = _resolve_window_start(config, should_use_incremental_field, db_incremental_field_last_value)
        window_start = _format_datetime(start) if start is not None else None

    # runs/query requires at least one of session/id/parent_run/trace/reference_example in the
    # body (a 400 otherwise) — there's no such thing as an unscoped query across a workspace.
    session_ids = _list_session_ids(session, headers, base_url, logger)
    if not session_ids:
        logger.debug("LangSmith: no tracing projects in workspace, nothing to sync for runs")
        return

    body: dict[str, Any] = {
        "limit": config.page_size,
        "select": RUNS_SELECT_FIELDS,
        # Ascending by start time so cursor pagination walks forward deterministically from the
        # window bound. The watermark still only persists at job end (sort_mode="desc") since we
        # can't verify the ordering guarantee across every LangSmith deployment.
        "order": "asc",
        "session": session_ids,
    }
    if window_start:
        body["start_time"] = window_start

    # Digests, not the cursors themselves: `next_cursor` is attacker-controlled and can be nearly as
    # large as a whole response, so retaining the raw values would let a stream of unique cursors
    # grow this set without bound. A fixed-size digest is all cycle detection needs.
    seen_cursors: set[bytes] = set()
    pages = 0
    while True:
        page_cursor = cursor
        page_body = {**body, "cursor": page_cursor} if page_cursor else dict(body)
        data = _fetch_page(session, url, headers, logger, json_body=page_body)

        runs = data.get("runs", []) if isinstance(data, dict) else []
        if not runs:
            break

        next_cursor = (data.get("cursors") or {}).get("next")

        for item in runs:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more pages remain) so a crash re-reads this
                # page rather than skipping it — merge dedupes on the primary key.
                if next_cursor:
                    resumable_source_manager.save_state(
                        LangSmithResumeConfig(cursor=page_cursor, window_start=window_start)
                    )

        if not next_cursor:
            break

        # Reject an absurdly large cursor before it's echoed back or remembered.
        if len(next_cursor.encode()) > MAX_CURSOR_BYTES:
            raise LangSmithResponseTooLargeError(
                f"LangSmith returned an oversized pagination cursor (> {MAX_CURSOR_BYTES} bytes)"
            )

        # A host that hands back a cursor it already gave us (or the one we just sent) is looping;
        # retrying would re-hit it, so fail for good instead of spinning until the activity timeout.
        cursor_digest = hashlib.sha256(next_cursor.encode()).digest()
        if next_cursor == page_cursor or cursor_digest in seen_cursors:
            raise LangSmithRepeatedCursorError(REPEATED_CURSOR_ERROR)
        seen_cursors.add(cursor_digest)

        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            # Flush any batched-but-unyielded items from this page before checkpointing the next
            # page — resuming from next_cursor skips this page, so an unflushed partial batch is lost.
            if batcher.should_yield(include_incomplete_chunk=True):
                yield batcher.get_table()
            # Checkpoint the next page and end this attempt; the resume path picks it up so a
            # legitimate oversized import continues without one attempt monopolising a worker.
            resumable_source_manager.save_state(LangSmithResumeConfig(cursor=next_cursor, window_start=window_start))
            raise LangSmithPageLimitError(
                f"LangSmith runs import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint"
            )

        cursor = next_cursor


def _get_offset_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    config: LangSmithEndpointConfig,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    """Page through a GET list endpoint with offset/limit. Responses are bare JSON arrays; a page
    shorter than the limit is the last page."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        offset = resume.offset or 0
        window_start = resume.window_start
        logger.debug(f"LangSmith: resuming {config.name} from offset={offset}")
    else:
        offset = 0
        start = _resolve_window_start(config, should_use_incremental_field, db_incremental_field_last_value)
        window_start = _format_datetime(start) if start is not None else None

    params: dict[str, Any] = {"limit": config.page_size}
    if config.window_param and window_start:
        params[config.window_param] = window_start

    pages = 0
    while True:
        page_offset = offset
        url = f"{base_url}{config.path}?{urlencode({**params, 'offset': page_offset})}"
        data = _fetch_page(session, url, headers, logger)

        rows = data if isinstance(data, list) else []
        if not rows:
            break

        is_last_page = len(rows) < config.page_size

        for item in rows:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-reads this page rather than skipping it.
                if not is_last_page:
                    resumable_source_manager.save_state(
                        LangSmithResumeConfig(offset=page_offset, window_start=window_start)
                    )

        if is_last_page:
            break
        offset = page_offset + config.page_size

        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            # Flush any batched-but-unyielded items from this page before checkpointing the next
            # offset — resuming skips this page, so an unflushed partial batch is lost.
            if batcher.should_yield(include_incomplete_chunk=True):
                yield batcher.get_table()
            # A host that returns a full page at every offset forever would page without end;
            # checkpoint the next offset and end this attempt so the resume path continues a real
            # oversized import without one attempt holding a worker until the activity timeout.
            resumable_source_manager.save_state(LangSmithResumeConfig(offset=offset, window_start=window_start))
            raise LangSmithPageLimitError(
                f"LangSmith {config.name} import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint"
            )


def _get_examples_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    config: LangSmithEndpointConfig,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    """Page GET /examples for every dataset in the workspace.

    Examples belong to a dataset, and GET /examples rejects a request that doesn't scope to one
    (a 400 otherwise), so this walks each dataset id and pages that dataset's examples with a
    `dataset` filter. Examples are full-refresh only (no server-side window), so there's no
    incremental watermark to pin — the resume tracks which dataset and offset an interrupted run
    was on."""
    dataset_ids = _list_dataset_ids(session, headers, base_url, logger)
    if not dataset_ids:
        logger.debug("LangSmith: no datasets in workspace, nothing to sync for examples")
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # Only resume into a dataset that still exists; a deleted one restarts the sweep from the top
    # so no dataset is silently skipped.
    resume_into_dataset = resume.dataset_id if resume is not None and resume.dataset_id in dataset_ids else None
    resume_offset = resume.offset if resume is not None else None
    start_index = dataset_ids.index(resume_into_dataset) if resume_into_dataset is not None else 0
    if resume_into_dataset is not None:
        logger.debug(f"LangSmith: resuming examples from dataset={resume_into_dataset} offset={resume_offset}")

    pages = 0
    for index in range(start_index, len(dataset_ids)):
        dataset_id = dataset_ids[index]
        is_last_dataset = index == len(dataset_ids) - 1
        if index == start_index and resume_into_dataset is not None:
            offset = resume_offset or 0
        else:
            offset = 0
            # Checkpoint the dataset boundary before reading it, so a crash resumes at this dataset
            # rather than re-reading the previous one.
            resumable_source_manager.save_state(LangSmithResumeConfig(dataset_id=dataset_id, offset=0))

        while True:
            page_offset = offset
            url = f"{base_url}{config.path}?{urlencode({'dataset': dataset_id, 'limit': config.page_size, 'offset': page_offset})}"
            data = _fetch_page(session, url, headers, logger)
            # Count every request, including a short first page, against the per-run limit. A
            # dataset whose examples fit on one page must still cost one request — otherwise a
            # host serving many datasets (bounded only by MAX_DATASET_IDS_BYTES) each with a
            # single short page pages forever without ever tripping MAX_PAGES_PER_RUN.
            pages += 1

            rows = data if isinstance(data, list) else []
            is_last_page = not rows or len(rows) < config.page_size

            for item in rows:
                batcher.batch(item)
                if batcher.should_yield():
                    yield batcher.get_table()
                    # Save AFTER yielding so a crash re-reads this page rather than skipping it.
                    # Skip only on the final page of the final dataset — the run is finishing.
                    if not (is_last_page and is_last_dataset):
                        resumable_source_manager.save_state(
                            LangSmithResumeConfig(dataset_id=dataset_id, offset=page_offset)
                        )

            run_is_finished = is_last_page and is_last_dataset
            if pages >= MAX_PAGES_PER_RUN and not run_is_finished:
                # Flush any batched-but-unyielded items before checkpointing where to resume —
                # resuming skips this page, so an unflushed partial batch is lost.
                if batcher.should_yield(include_incomplete_chunk=True):
                    yield batcher.get_table()
                if is_last_page:
                    # This dataset is exhausted; resume picks up at the start of the next one.
                    next_dataset_id = dataset_ids[index + 1]
                    resumable_source_manager.save_state(LangSmithResumeConfig(dataset_id=next_dataset_id, offset=0))
                else:
                    resumable_source_manager.save_state(
                        LangSmithResumeConfig(dataset_id=dataset_id, offset=page_offset + config.page_size)
                    )
                raise LangSmithPageLimitError(
                    f"LangSmith examples import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint"
                )

            if is_last_page:
                break
            offset = page_offset + config.page_size


def get_rows(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = LANGSMITH_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    # Re-check at run time (not just at source-create): the host could have been edited or now
    # resolve to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(base_url, team_id)

    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # Redact the key and never follow a redirect off the validated host. Keep response bodies out
    # of HTTP sample capture — run inputs/outputs are raw LLM prompts and completions that can
    # carry secrets or personal data the name-based scrubber won't recognize.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False)

    if config.scoped_by_dataset:
        pager = _get_examples_rows
    elif config.pagination == "cursor":
        pager = _get_runs_rows
    else:
        pager = _get_offset_rows
    yield from pager(
        session,
        headers,
        base_url,
        config,
        batcher,
        resumable_source_manager,
        logger,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def langsmith_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LANGSMITH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
