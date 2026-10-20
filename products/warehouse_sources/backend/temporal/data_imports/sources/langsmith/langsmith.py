import re
import json
import hashlib
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.boundary_checkpoint import (
    BoundaryCheckpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.settings import (
    DEFAULT_BASE_URL,
    LANGSMITH_ENDPOINTS,
    RUNS_HEAVY_SELECT_FIELDS,
    RUNS_SELECT_FIELDS,
    LangSmithEndpointConfig,
)

# Returned when the resolved host resolves to a private/internal address on cloud (SSRF guard).
HOST_NOT_ALLOWED_ERROR = "LangSmith host is not allowed"

# Returned when a cloud connection would send the API key over plaintext HTTP.
INSECURE_SCHEME_ERROR = "LangSmith host must use https"

# Raised (and registered retryable) when the API answers 429 or 5xx. `_fetch_page` retries it
# inline; once that budget exhausts, Temporal retries the activity from the saved checkpoint.
RETRYABLE_API_ERROR = "LangSmith API error (retryable)"

# Raised (and registered non-retryable) when the host loops the runs cursor. A host that returns a
# cursor we've already paged is stuck or hostile; retrying re-hits the same cursor, so fail for good.
REPEATED_CURSOR_ERROR = "LangSmith returned a repeated pagination cursor"

# Raised (and registered non-retryable) when a page body exceeds MAX_RESPONSE_BYTES. The same page
# is re-requested on every retry, so the cap is hit again deterministically — stop immediately.
RESPONSE_TOO_LARGE_ERROR = "LangSmith API returned an oversized response"

# Raised (and registered non-retryable) when the host returns oversized pagination data: a cursor
# past MAX_CURSOR_BYTES, or an id set past MAX_PARENT_IDS_BYTES while scoping a query. Every retry walks the same pages and collects the same oversized data.
PAGINATION_TOO_LARGE_ERROR = "LangSmith returned oversized pagination data"

# Raised (and registered non-retryable) when a single runs page stays over MAX_RESPONSE_BYTES even at
# the minimum limit. A page that big has runs with very large inputs/outputs; halving the page can't
# help below one run, so fail with guidance instead of retrying the same wall.
RUNS_PAGE_TOO_LARGE_ERROR = "LangSmith runs page too large even at the minimum page size"

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

# Smallest runs page we shrink to when a full page exceeds MAX_RESPONSE_BYTES. A single run still
# carries full inputs/outputs, so one run per request is the floor; below it there is nothing left to
# halve. See _fetch_runs_page.
MIN_RUNS_PAGE_SIZE = 1

# Bound how many pages one activity attempt walks. A hostile host can otherwise return a full page
# with a fresh cursor/offset forever and hold a worker until the week-long activity timeout. On the
# cap we persist the resume checkpoint and raise, so the attempt ends but a legitimate oversized
# import continues from the checkpoint on the next attempt. Generous: the runs rate limits alone
# make hitting this in one attempt take days.
MAX_PAGES_PER_RUN = 50_000

# Cap the total bytes of parent ids (projects, datasets, annotation queues) accumulated while scoping
# a query. `host` is user-controlled and returns arbitrary `id` strings on every listing page, so
# without a cumulative cap a host could return unboundedly many (or oversized) ids across thousands
# of pages — well before MAX_PAGES_PER_RUN trips — and exhaust a shared import worker's memory. ~58k
# real UUIDs' worth, far beyond any legitimate workspace's count.
MAX_PARENT_IDS_BYTES = 2 * 1024 * 1024

# Bound what one log line can carry out of a page. The host chooses how many runs it returns and
# how long each id is, so an unbounded line lets it turn a warning into an oversized log event.
MAX_LOGGED_RUN_IDS = 5
MAX_LOGGED_RUN_ID_CHARS = 64


class LangSmithRetryableError(Exception):
    pass


class LangSmithHostNotAllowedError(Exception):
    """The resolved host is blocked (SSRF guard) or tried to redirect the authenticated request."""

    pass


class LangSmithResponseTooLargeError(Exception):
    """The host returned a body larger than `MAX_RESPONSE_BYTES` — refused before buffering it all.

    `get_non_retryable_errors` matches on message text, so the sentinel is prefixed here rather than
    at the raise site: a message without it is retried for the whole activity budget.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"{RESPONSE_TOO_LARGE_ERROR}: {detail}")


class LangSmithPaginationTooLargeError(Exception):
    """The host returned oversized pagination data: a cursor, or the ids collected to scope a query.

    Separate from `LangSmithResponseTooLargeError` because the runs page shrinker catches that one,
    and shrinking a page cannot fix either of these limits. Same sentinel prefixing as above.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"{PAGINATION_TOO_LARGE_ERROR}: {detail}")


class LangSmithPageLimitError(Exception):
    """One activity attempt walked `MAX_PAGES_PER_RUN` pages. Retryable: resume from the checkpoint."""

    pass


class LangSmithRepeatedCursorError(Exception):
    """The host looped the runs cursor. Non-retryable (see REPEATED_CURSOR_ERROR) — retrying re-loops."""

    pass


class LangSmithRunsPageTooLargeError(Exception):
    """A single runs page stayed over the cap at the minimum page size. Non-retryable — see
    RUNS_PAGE_TOO_LARGE_ERROR."""

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
            raise LangSmithResponseTooLargeError(f"body over {cap} bytes")
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
    # Parent (dataset, annotation queue, or project) being paged when a parent-scoped run was
    # interrupted, so the resume needs both which parent and the offset or cursor within it. None for
    # every other endpoint.
    parent_id: str | None = None


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


_LANGSMITH_UNREACHABLE_ERROR = "Couldn't reach LangSmith to validate your API key. Try again in a few minutes."


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
    except requests.exceptions.RequestException:
        # A network failure or timeout is transient and unrelated to the key; the raw exception
        # embeds the URL and gives the user nothing actionable.
        return False, _LANGSMITH_UNREACHABLE_ERROR

    if status_code == 200:
        return True, None
    if status_code == 401:
        return (
            False,
            "Your LangSmith API key is invalid or has been revoked. Create a new key in your "
            "LangSmith settings under API keys, then reconnect.",
        )
    if status_code == 403:
        return (
            False,
            "Your LangSmith API key can't read this workspace. Create a key in the workspace you "
            "want to sync, then reconnect.",
        )
    if status_code == 404:
        return (
            False,
            "PostHog reached this host but found no LangSmith API there. Check the host field, then try again.",
        )
    # 429 (rate limit) and 5xx are transient LangSmith-side problems, not a bad key, so surface a
    # retry hint rather than telling the user to fix credentials they can't fix.
    if status_code == 429 or status_code >= 500:
        return False, _LANGSMITH_UNREACHABLE_ERROR
    return (
        False,
        "Couldn't validate your LangSmith API key. Check that it's a valid key from your LangSmith "
        "settings, then try again.",
    )


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
            raise LangSmithRetryableError(f"{RETRYABLE_API_ERROR}: status={response.status_code}, url={url}")

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


def _runs_select_fields(config: LangSmithEndpointConfig, enabled_columns: list[str] | None) -> list[str]:
    """The `select` to send to runs/query for the columns the schema keeps.

    MAX_RESPONSE_BYTES is enforced while the body is read, so a column the pipeline drops after the
    fetch still costs its bytes on the wire. The primary key and the partition key are kept whatever
    the user picked, because the merge and the Delta layout need them. `None` and an empty list mean
    what they mean to `apply_enabled_columns_projection`: every column, and only the required ones.
    """
    if enabled_columns is None:
        return list(RUNS_SELECT_FIELDS)
    required = {*config.primary_keys, *([config.partition_key] if config.partition_key else [])}
    wanted = {*enabled_columns} | required
    return [name for name in RUNS_SELECT_FIELDS if name in wanted]


def _bounded_run_ids(runs: list[Any]) -> list[str]:
    """A sample of run ids, capped in count and length, for a log line."""
    return [str(run.get("id"))[:MAX_LOGGED_RUN_ID_CHARS] for run in runs[:MAX_LOGGED_RUN_IDS] if isinstance(run, dict)]


def _fetch_runs_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    body: dict[str, Any],
    page_cursor: str | None,
    limit: int,
) -> tuple[Any, int]:
    """POST one runs page, halving `limit` and re-requesting the same cursor when the page is oversized.

    A legitimate workspace with large prompt payloads can push a full page past MAX_RESPONSE_BYTES.
    Halving the page and retrying the same cursor lets the sync move forward without skipping runs.
    Returns the page data and the limit that fetched it, so the caller keeps the shrunk size for the
    next pages.

    One run over the cap on its own cannot be halved further, so the last attempt re-requests it
    without the heavy fields: the row lands with null inputs/outputs instead of ending the table.
    That narrowed response is also the only way to learn the run id, because an oversized body is
    refused before it can be parsed. Raises LangSmithRunsPageTooLargeError when it is oversized too.
    """
    heavy_fields_dropped = False
    while True:
        page_body = {**body, "limit": limit}
        if heavy_fields_dropped:
            page_body["select"] = [name for name in body["select"] if name not in RUNS_HEAVY_SELECT_FIELDS]
        if page_cursor:
            page_body["cursor"] = page_cursor
        try:
            data = _fetch_page(session, url, headers, logger, json_body=page_body)
        except LangSmithResponseTooLargeError:
            if limit > MIN_RUNS_PAGE_SIZE:
                limit = max(MIN_RUNS_PAGE_SIZE, limit // 2)
                logger.warning(
                    f"LangSmith runs page exceeded the response cap; retrying same cursor with limit={limit}"
                )
                continue
            if heavy_fields_dropped or not any(name in body["select"] for name in RUNS_HEAVY_SELECT_FIELDS):
                raise LangSmithRunsPageTooLargeError(RUNS_PAGE_TOO_LARGE_ERROR)
            heavy_fields_dropped = True
            logger.warning(
                "LangSmith run exceeded the response cap at the minimum page size; retrying the same cursor without "
                f"{', '.join(RUNS_HEAVY_SELECT_FIELDS)}"
            )
            continue

        if heavy_fields_dropped:
            runs = data.get("runs", []) if isinstance(data, dict) else []
            logger.warning(
                f"LangSmith imported {len(runs)} run(s) without {', '.join(RUNS_HEAVY_SELECT_FIELDS)} because they "
                f"exceeded the response cap: run_ids={_bounded_run_ids(runs)}"
            )
        return data, limit


def _list_parent_ids(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    parent_name: str,
    child_name: str,
    params: dict[str, Any] | None = None,
) -> list[str]:
    """Collect every id of the `parent_name` endpoint in the workspace.

    runs/query rejects a request that doesn't scope to at least one session, GET /examples one that
    doesn't scope to a dataset, and threads and annotation-queue runs are listed per project or per
    queue. These syncs cover the whole workspace, so they scope by every parent id instead.
    """
    parent = LANGSMITH_ENDPOINTS[parent_name]
    ids: list[str] = []
    ids_bytes = 0
    offset = 0
    pages = 0
    while True:
        url = f"{base_url}{parent.path}?{urlencode({**(params or {}), 'limit': parent.page_size, 'offset': offset})}"
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
            if ids_bytes > MAX_PARENT_IDS_BYTES:
                raise LangSmithPaginationTooLargeError(
                    f"the set of {parent_name} ids went over {MAX_PARENT_IDS_BYTES} bytes "
                    f"while scoping the {child_name} query"
                )
        if len(rows) < parent.page_size:
            break
        offset += parent.page_size
        # Same hostile-host guard as the other paginators: a host returning a full page forever
        # must not hold the worker until the activity timeout.
        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            raise LangSmithPageLimitError(
                f"LangSmith {parent_name} listing hit the {MAX_PAGES_PER_RUN}-page limit while scoping the {child_name} query"
            )
    return ids


def _check_next_cursor(next_cursor: str, page_cursor: str | None, seen_cursors: set[bytes], endpoint: str) -> None:
    """Reject a cursor that is absurdly large or that loops, before it's echoed back or remembered.

    `seen_cursors` holds digests, not the cursors themselves: `next_cursor` is attacker-controlled and
    can be nearly as large as a whole response, so retaining the raw values would let a stream of
    unique cursors grow the set without bound. A fixed-size digest is all cycle detection needs.
    """
    if len(next_cursor.encode()) > MAX_CURSOR_BYTES:
        raise LangSmithPaginationTooLargeError(f"the {endpoint} cursor went over {MAX_CURSOR_BYTES} bytes")

    # A host that hands back a cursor it already gave us (or the one we just sent) is looping;
    # retrying would re-hit it, so fail for good instead of spinning until the activity timeout.
    cursor_digest = hashlib.sha256(next_cursor.encode()).digest()
    if next_cursor == page_cursor or cursor_digest in seen_cursors:
        raise LangSmithRepeatedCursorError(REPEATED_CURSOR_ERROR)
    seen_cursors.add(cursor_digest)


def _shape_rows(config: LangSmithEndpointConfig, rows: list[Any], parent_id: str) -> list[Any]:
    if not config.parent_id_field and not config.dropped_fields:
        return rows
    shaped: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        shaped_row = {key: value for key, value in row.items() if key not in config.dropped_fields}
        if config.parent_id_field:
            shaped_row[config.parent_id_field] = parent_id
        shaped.append(shaped_row)
    return shaped


def _emit_batches(
    batcher: Batcher,
    rows: list[Any],
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    resume_state: LangSmithResumeConfig,
    *,
    is_final_page: bool,
) -> Iterator[Any]:
    """Batch one page of rows, yielding a table each time one fills.

    `resume_state` is saved AFTER yielding so a crash re-reads this page rather than skipping it,
    because merge dedupes on the primary key. Nothing is saved on the final page, where the run is
    finishing and there is no next page to resume to.
    """
    for item in rows:
        batcher.batch(item)
        if batcher.should_yield():
            yield batcher.get_table()
            if not is_final_page:
                resumable_source_manager.save_state(resume_state)


def _stop_at_page_limit(
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    resume_state: LangSmithResumeConfig,
    message: str,
) -> Iterator[Any]:
    """End this attempt at MAX_PAGES_PER_RUN, checkpointing where the next attempt picks up.

    Flushes any batched-but-unyielded items first: resuming from `resume_state` skips the page they
    came from, so an unflushed partial batch is lost. The raise ends the attempt without one
    attempt monopolising a worker, and a legitimate oversized import continues from the checkpoint.
    """
    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()
    resumable_source_manager.save_state(resume_state)
    # A safe point keeps the cursor saved after the last yield. The source holds no rows here.
    resumable_source_manager.safe_point()
    raise LangSmithPageLimitError(message)


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
    select_fields: list[str],
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
    session_ids = _list_parent_ids(session, headers, base_url, logger, "projects", config.name)
    if not session_ids:
        logger.debug("LangSmith: no tracing projects in workspace, nothing to sync for runs")
        return

    body: dict[str, Any] = {
        "select": select_fields,
        # Ascending by start time so cursor pagination walks forward deterministically from the
        # window bound. The watermark still only persists at job end (sort_mode="desc") since we
        # can't verify the ordering guarantee across every LangSmith deployment.
        "order": "asc",
        "session": session_ids,
    }
    if window_start:
        body["start_time"] = window_start

    seen_cursors: set[bytes] = set()
    pages = 0
    # Shrinks (and stays shrunk) when a page trips MAX_RESPONSE_BYTES — see _fetch_runs_page.
    limit = config.page_size
    while True:
        page_cursor = cursor
        data, limit = _fetch_runs_page(session, url, headers, logger, body, page_cursor, limit)

        runs = data.get("runs", []) if isinstance(data, dict) else []
        if not runs:
            break

        next_cursor = (data.get("cursors") or {}).get("next")

        yield from _emit_batches(
            batcher,
            runs,
            resumable_source_manager,
            LangSmithResumeConfig(cursor=page_cursor, window_start=window_start),
            is_final_page=not next_cursor,
        )

        if not next_cursor:
            break

        _check_next_cursor(next_cursor, page_cursor, seen_cursors, config.name)

        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            yield from _stop_at_page_limit(
                batcher,
                resumable_source_manager,
                LangSmithResumeConfig(cursor=next_cursor, window_start=window_start),
                f"LangSmith runs import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint",
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

        yield from _emit_batches(
            batcher,
            rows,
            resumable_source_manager,
            LangSmithResumeConfig(offset=page_offset, window_start=window_start),
            is_final_page=is_last_page,
        )

        if is_last_page:
            break
        offset = page_offset + config.page_size

        pages += 1
        if pages >= MAX_PAGES_PER_RUN:
            # A host that returns a full page at every offset forever would page without end.
            yield from _stop_at_page_limit(
                batcher,
                resumable_source_manager,
                LangSmithResumeConfig(offset=offset, window_start=window_start),
                f"LangSmith {config.name} import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint",
            )


def _parent_start_position(
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    parent_ids: list[str],
    logger: FilteringBoundLogger,
) -> tuple[int, LangSmithResumeConfig | None]:
    """Return the parent index an interrupted parent-scoped run picks back up at, and the saved state
    holding the position within that parent. The state is None when there is no usable checkpoint
    and the sweep starts over.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # Only resume into a parent that still exists; a deleted one restarts the sweep from the top
    # so no parent is silently skipped.
    if resume is None or resume.parent_id not in parent_ids:
        return 0, None
    logger.debug(f"LangSmith: resuming from parent={resume.parent_id} offset={resume.offset} cursor={resume.cursor}")
    return parent_ids.index(resume.parent_id), resume


def _parent_url(base_url: str, config: LangSmithEndpointConfig, parent_id: str) -> str:
    # Parent ids come from the user-controlled host, so encode them before they enter the path.
    return f"{base_url}{config.path.replace('{parent_id}', quote(parent_id, safe=''))}"


def _get_parent_scoped_rows(
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
    """Page an offset/limit GET endpoint once for every parent id in the workspace.

    GET /examples rejects a request that doesn't scope to a dataset (a 400 otherwise), and
    annotation-queue runs are only listed per queue, so this walks each parent id and pages its rows.
    These endpoints are full-refresh only (no server-side window), so there's no incremental
    watermark to pin — the resume tracks which parent and offset an interrupted run was on."""
    assert config.parent is not None
    parent_ids = _list_parent_ids(
        session, headers, base_url, logger, config.parent, config.name, config.parent_list_params
    )
    if not parent_ids:
        logger.debug(f"LangSmith: no {config.parent} in workspace, nothing to sync for {config.name}")
        return

    start_index, resume = _parent_start_position(resumable_source_manager, parent_ids, logger)

    pages = 0
    parent_checkpoint = BoundaryCheckpoint(batcher, resumable_source_manager)
    for index in range(start_index, len(parent_ids)):
        parent_id = parent_ids[index]
        is_last_parent = index == len(parent_ids) - 1
        if index == start_index and resume is not None:
            offset = resume.offset or 0
        else:
            offset = 0
            # Checkpoint the parent boundary before reading it, so a crash resumes at this parent
            # rather than re-reading the previous one. The batcher can hold rows of the previous
            # parent, and a checkpoint at this parent skips them.
            yield from parent_checkpoint.save(LangSmithResumeConfig(parent_id=parent_id, offset=0))

        while True:
            page_offset = offset
            params: dict[str, Any] = {"limit": config.page_size, "offset": page_offset}
            if config.parent_query_param:
                params = {config.parent_query_param: parent_id, **params}
            url = f"{_parent_url(base_url, config, parent_id)}?{urlencode(params)}"
            data = _fetch_page(session, url, headers, logger)
            # Count every request, including a short first page, against the per-run limit. A
            # parent whose rows fit on one page must still cost one request — otherwise a host
            # serving many parents (bounded only by MAX_PARENT_IDS_BYTES) each with a single short
            # page pages forever without ever tripping MAX_PAGES_PER_RUN.
            pages += 1

            rows = data if isinstance(data, list) else []
            is_last_page = not rows or len(rows) < config.page_size

            run_is_finished = is_last_page and is_last_parent
            yield from _emit_batches(
                batcher,
                _shape_rows(config, rows, parent_id),
                resumable_source_manager,
                LangSmithResumeConfig(parent_id=parent_id, offset=page_offset),
                is_final_page=run_is_finished,
            )

            if pages >= MAX_PAGES_PER_RUN and not run_is_finished:
                next_state = (
                    # This parent is exhausted; resume picks up at the start of the next one.
                    LangSmithResumeConfig(parent_id=parent_ids[index + 1], offset=0)
                    if is_last_page
                    else LangSmithResumeConfig(parent_id=parent_id, offset=page_offset + config.page_size)
                )
                yield from _stop_at_page_limit(
                    batcher,
                    resumable_source_manager,
                    next_state,
                    f"LangSmith {config.name} import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint",
                )

            if is_last_page:
                break
            offset = page_offset + config.page_size


def _get_threads_rows(
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
    """Page POST /v2/threads/query with the body cursor, once for every tracing project.

    The query takes a single `project_id`, so this walks each project. The API defaults
    `min_start_time` to one day ago, so the lookback is always sent, and a resume keeps the window
    the interrupted run started with so its cursor still points into the same result set."""
    assert config.parent is not None
    project_ids = _list_parent_ids(
        session, headers, base_url, logger, config.parent, config.name, config.parent_list_params
    )
    if not project_ids:
        logger.debug(f"LangSmith: no tracing projects in workspace, nothing to sync for {config.name}")
        return

    start_index, resume = _parent_start_position(resumable_source_manager, project_ids, logger)
    if resume is not None and resume.window_start:
        window_start: str | None = resume.window_start
    elif config.default_lookback_days:
        window_start = _format_datetime(datetime.now(UTC) - timedelta(days=config.default_lookback_days))
    else:
        window_start = None

    url = f"{base_url}{config.path}"
    pages = 0
    project_checkpoint = BoundaryCheckpoint(batcher, resumable_source_manager)
    for index in range(start_index, len(project_ids)):
        project_id = project_ids[index]
        is_last_project = index == len(project_ids) - 1
        if index == start_index and resume is not None:
            cursor = resume.cursor
        else:
            cursor = None
            yield from project_checkpoint.save(LangSmithResumeConfig(parent_id=project_id, window_start=window_start))

        seen_cursors: set[bytes] = set()
        while True:
            page_cursor = cursor
            body: dict[str, Any] = {"project_id": project_id, "page_size": config.page_size}
            if window_start:
                body["min_start_time"] = window_start
            if page_cursor:
                body["cursor"] = page_cursor
            data = _fetch_page(session, url, headers, logger, json_body=body)
            pages += 1

            page = data if isinstance(data, dict) else {}
            rows = page.get("items") if isinstance(page.get("items"), list) else []
            next_cursor = page.get("next_cursor") or None
            if next_cursor is not None:
                _check_next_cursor(str(next_cursor), page_cursor, seen_cursors, config.name)
            # A page can hold fewer threads than `page_size`, even none, before the last one, so only
            # a missing cursor ends the project.
            is_last_page = next_cursor is None

            run_is_finished = is_last_page and is_last_project
            yield from _emit_batches(
                batcher,
                _shape_rows(config, rows or [], project_id),
                resumable_source_manager,
                LangSmithResumeConfig(parent_id=project_id, cursor=page_cursor, window_start=window_start),
                is_final_page=run_is_finished,
            )

            if pages >= MAX_PAGES_PER_RUN and not run_is_finished:
                next_state = (
                    LangSmithResumeConfig(parent_id=project_ids[index + 1], window_start=window_start)
                    if is_last_page
                    else LangSmithResumeConfig(parent_id=project_id, cursor=str(next_cursor), window_start=window_start)
                )
                yield from _stop_at_page_limit(
                    batcher,
                    resumable_source_manager,
                    next_state,
                    f"LangSmith {config.name} import hit the {MAX_PAGES_PER_RUN}-page per-attempt limit; resuming from checkpoint",
                )

            if is_last_page:
                break
            cursor = str(next_cursor)


def _get_single_page_rows(
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
    """GET a list endpoint that returns every row in one unpaginated JSON array."""
    data = _fetch_page(session, f"{base_url}{config.path}", headers, logger)
    rows = data if isinstance(data, list) else []
    yield from _emit_batches(batcher, rows, resumable_source_manager, LangSmithResumeConfig(), is_final_page=True)


def get_rows(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    enabled_columns: list[str] | None = None,
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

    pager: Callable[..., Iterator[Any]]
    if config.pagination == "none":
        pager = _get_single_page_rows
    elif config.pagination == "cursor" and config.parent:
        pager = _get_threads_rows
    elif config.parent:
        pager = _get_parent_scoped_rows
    elif config.pagination == "cursor":
        # Bound here because only runs has a server-side select to narrow.
        pager = partial(_get_runs_rows, select_fields=_runs_select_fields(config, enabled_columns))
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
    enabled_columns: Optional[list[str]] = None,
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
            enabled_columns=enabled_columns,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
