import re
import json
import time
import threading
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
import structlog
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.settings import (
    SOURCEGRAPH_ENDPOINTS,
    SourcegraphEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
# Cap for connections without cursor pagination (organizations). Sourcegraph instances rarely
# have more than a handful of orgs; a truncated fetch is logged.
UNPAGINATED_FETCH_LIMIT = 1000

# The Sourcegraph host is customer-controlled, so its cursor pagination is untrusted: a malicious
# or compromised instance can hand back an endless run of full pages with fresh cursors and keep an
# import worker occupied until the activity's week-long timeout. Bound a single run by both page
# count and cumulative wall-clock so an endless (or pathologically slow) stream fails the sync
# instead of holding the worker — a real instance completes well inside both. At page_size 100 the
# page cap is ~10M rows; the deadline sits far below the activity ceiling.
MAX_PAGES_PER_RUN = 100_000
MAX_PAGINATION_SECONDS = 6 * 60 * 60

HOST_NOT_ALLOWED_ERROR = "Sourcegraph host is not allowed"
GRAPHQL_ERROR_PREFIX = "Sourcegraph GraphQL error"

RESPONSE_TOO_LARGE_ERROR = "Sourcegraph API response exceeded the size limit"
RESPONSE_TIMEOUT_ERROR = "Sourcegraph API response exceeded the download time limit"

# The Sourcegraph host is customer-controlled (self-hosted instances), so responses are
# streamed and read under a byte cap — an arbitrarily large (or endless) 200 body must fail
# the sync instead of exhausting worker memory. The cap applies to decoded bytes, so a gzip
# bomb can't slip past it.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
# The per-read timeout only bounds the gap between chunks, so a server can trickle one byte
# just before each read timeout and keep a worker occupied indefinitely. A monotonic
# total-transfer deadline caps how long a single body read may take end to end, independent
# of how the bytes are paced. A single streamed read blocks until a whole chunk (or EOF)
# arrives, so the in-loop deadline check can't interrupt it; a watchdog force-closes the
# response once the deadline passes, unblocking that read so this slow-drip path fails the sync.
MAX_RESPONSE_SECONDS = 600
# Bytes read from an error body for a diagnostic message. Error bodies are never needed in
# full, so only a short bounded snippet is ever pulled into memory.
_ERROR_SNIPPET_BYTES = 2048

module_logger = structlog.get_logger(__name__)


class SourcegraphRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SourcegraphHostNotAllowedError(Exception):
    pass


class SourcegraphResponseTooLargeError(Exception):
    pass


class SourcegraphResponseTimeoutError(Exception):
    pass


class SourcegraphPaginationLimitError(Exception):
    """A single run walked more pages, or ran longer, than the per-run bounds allow."""

    pass


def _read_bounded(response: requests.Response, max_bytes: int, max_seconds: float = MAX_RESPONSE_SECONDS) -> bytes:
    """Read a streamed response body under both a byte cap and a total-transfer deadline.

    A single ``iter_content`` read blocks until a whole chunk (or EOF) arrives, so the in-loop
    deadline check alone can't stop a slow-drip body that trickles bytes under the per-read socket
    timeout — the loop never regains control to check the clock. A watchdog thread force-closes the
    response once the deadline passes, which unblocks that read so the sync fails instead of holding
    the worker indefinitely. The in-loop check still covers bodies that arrive as many quick chunks.
    """
    total = 0
    chunks: list[bytes] = []
    deadline = time.monotonic() + max_seconds
    finished = threading.Event()
    timed_out = threading.Event()

    def _abort_on_deadline() -> None:
        if not finished.wait(max_seconds):
            timed_out.set()
            response.close()

    watchdog = threading.Thread(target=_abort_on_deadline, daemon=True)
    watchdog.start()

    read_complete = False
    try:
        for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
            if timed_out.is_set():
                break
            total += len(chunk)
            if total > max_bytes:
                raise SourcegraphResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR} ({max_bytes} bytes)")
            if time.monotonic() > deadline:
                raise SourcegraphResponseTimeoutError(f"{RESPONSE_TIMEOUT_ERROR} ({max_seconds:g}s)")
            chunks.append(chunk)
        read_complete = True
    except Exception:
        # Force-closing the response mid-read surfaces here as a transport error; when the watchdog
        # fired, report the deadline rather than the incidental socket failure.
        if not timed_out.is_set():
            raise
    finally:
        finished.set()

    if timed_out.is_set() and not read_complete:
        raise SourcegraphResponseTimeoutError(f"{RESPONSE_TIMEOUT_ERROR} ({max_seconds:g}s)")
    return b"".join(chunks)


def _error_snippet(response: requests.Response) -> str:
    try:
        chunk = next(response.iter_content(chunk_size=_ERROR_SNIPPET_BYTES), b"")
        return chunk[:_ERROR_SNIPPET_BYTES].decode("utf-8", errors="replace")
    except Exception:
        return ""


class SourcegraphQueryError(Exception):
    """A GraphQL-level error returned with HTTP 200 (e.g. missing site-admin permissions)."""

    pass


@dataclasses.dataclass
class SourcegraphResumeConfig:
    # Relay `endCursor` of the last fully-yielded page. None means "start from the first page".
    cursor: str | None = None


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare Sourcegraph host.

    Accepts values like ``sourcegraph.example.com``, ``https://sourcegraph.example.com/``,
    or ``sourcegraph.example.com/.api/graphql`` and returns ``sourcegraph.example.com``.
    """
    host = host.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0]
    return host.strip().rstrip("/")


def _graphql_url(host: str) -> str:
    return f"https://{normalize_host(host)}/.api/graphql"


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, SourcegraphRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type((SourcegraphRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _execute(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    """POST a GraphQL query and return the ``data`` payload, raising on transport or GraphQL errors."""
    # Don't follow redirects: the validated host could 3xx to an internal address, defeating
    # the host check done before the request (SSRF). `stream=True` so the body is only read
    # through `_read_bounded` / `_error_snippet` under a byte cap.
    with session.post(
        url,
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
        stream=True,
    ) as response:
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise SourcegraphRetryableError(
                f"Sourcegraph API error (retryable): status={response.status_code}, url={url}",
                retry_after=retry_after,
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
        # silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise SourcegraphHostNotAllowedError(
                f"Sourcegraph API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(
                f"Sourcegraph API error: status={response.status_code}, body={_error_snippet(response)}, url={url}"
            )
            response.raise_for_status()

        body = json.loads(_read_bounded(response, MAX_RESPONSE_BYTES))

    # Sourcegraph returns GraphQL-level failures (bad query, missing site-admin permissions)
    # with HTTP 200 and an `errors` array.
    errors = body.get("errors")
    if errors:
        messages = "; ".join(str(error.get("message", error)) for error in errors)
        raise SourcegraphQueryError(f"{GRAPHQL_ERROR_PREFIX}: {messages}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise SourcegraphQueryError(f"{GRAPHQL_ERROR_PREFIX}: response has no data payload")

    return data


def validate_credentials(
    host: str, access_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the API to confirm the access token is genuine.

    At source-create (``schema_name is None``) we only check the token itself via ``currentUser``
    — the admin-scoped connections (users, organizations) may legitimately be out of scope for a
    non-admin token. A scoped probe (``schema_name`` set) runs that endpoint's query with
    ``first: 1`` so permission failures surface for the specific table.
    """
    try:
        normalized = normalize_host(host)
    except Exception:
        return False, "Invalid Sourcegraph URL"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-:]+$", normalized):
        return False, "Invalid Sourcegraph URL"

    # The host is fully customer-controlled (self-hosted instances), so block hosts that resolve
    # to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    if schema_name is not None and schema_name in SOURCEGRAPH_ENDPOINTS:
        endpoint_config = SOURCEGRAPH_ENDPOINTS[schema_name]
        query = endpoint_config.query
        variables: dict[str, Any] = {"first": 1, "after": None} if endpoint_config.paginated else {"first": 1}
    else:
        query = "query { currentUser { username } }"
        variables = {}

    session = make_tracked_session()
    try:
        _execute(session, _graphql_url(normalized), _get_headers(access_token), query, variables, module_logger)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            return False, "Invalid Sourcegraph access token"
        return False, str(e)
    except SourcegraphQueryError as e:
        return False, str(e)
    except SourcegraphHostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except Exception as e:
        return False, str(e)

    return True, None


def get_endpoint_permissions(host: str, access_token: str, team_id: int, endpoints: list[str]) -> dict[str, str | None]:
    """Probe each endpoint with ``first: 1`` and report which are blocked by missing permissions.

    Only a genuine GraphQL-level denial (e.g. "must be site admin", "not authenticated") counts as
    a permission error — transient transport failures leave the endpoint marked reachable so this
    never blocks source creation.
    """
    results: dict[str, str | None] = dict.fromkeys(endpoints)
    session = make_tracked_session()
    headers = _get_headers(access_token)
    url = _graphql_url(host)

    for endpoint in endpoints:
        endpoint_config = SOURCEGRAPH_ENDPOINTS.get(endpoint)
        if endpoint_config is None:
            continue
        variables: dict[str, Any] = {"first": 1, "after": None} if endpoint_config.paginated else {"first": 1}
        try:
            _execute(session, url, headers, endpoint_config.query, variables, module_logger)
        except SourcegraphQueryError as e:
            results[endpoint] = str(e)
        except Exception:
            # A throttle, 5xx, or network blip is not a missing scope.
            continue

    return results


def get_rows(
    host: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SourcegraphResumeConfig],
    team_id: int,
) -> Iterator[Any]:
    config = SOURCEGRAPH_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_host(host), team_id)
    if not host_ok:
        raise SourcegraphHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    url = _graphql_url(host)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()

    if not config.paginated:
        data = _execute(session, url, headers, config.query, {"first": UNPAGINATED_FETCH_LIMIT}, logger)
        connection = data.get(config.data_path) or {}
        nodes = connection.get("nodes") or []
        total_count = connection.get("totalCount")
        if isinstance(total_count, int) and total_count > len(nodes):
            logger.warning(
                f"Sourcegraph: {endpoint} has {total_count} rows but the API exposes no cursor; "
                f"only the first {len(nodes)} were fetched"
            )
        if nodes:
            yield nodes
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after: str | None = resume.cursor if resume is not None else None
    if after:
        logger.debug(f"Sourcegraph: resuming {endpoint} from cursor {after}")

    pagination_deadline = time.monotonic() + MAX_PAGINATION_SECONDS
    pages_fetched = 0

    while True:
        data = _execute(session, url, headers, config.query, {"first": config.page_size, "after": after}, logger)
        connection = data.get(config.data_path) or {}
        nodes = connection.get("nodes") or []
        page_info = connection.get("pageInfo") or {}
        pages_fetched += 1

        if nodes:
            yield nodes

        end_cursor = page_info.get("endCursor")
        if not page_info.get("hasNextPage") or not end_cursor or not nodes:
            break

        # Save AFTER yielding so a crash re-fetches (and re-yields) the last page rather than
        # skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(SourcegraphResumeConfig(cursor=end_cursor))
        after = end_cursor

        # A customer-controlled host can hand back an endless run of full pages with fresh cursors;
        # fail the run once it crosses either per-run bound so it can't occupy a worker until the
        # activity's week-long timeout. The cursor is already checkpointed, so an activity retry
        # within this job resumes from here rather than re-walking from the start.
        if pages_fetched >= MAX_PAGES_PER_RUN:
            raise SourcegraphPaginationLimitError(
                f"Sourcegraph {endpoint} exceeded the per-run page limit ({MAX_PAGES_PER_RUN})"
            )
        if time.monotonic() > pagination_deadline:
            raise SourcegraphPaginationLimitError(
                f"Sourcegraph {endpoint} exceeded the per-run pagination deadline ({MAX_PAGINATION_SECONDS:g}s)"
            )


def sourcegraph_source(
    host: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SourcegraphResumeConfig],
    team_id: int,
) -> SourceResponse:
    endpoint_config: SourcegraphEndpointConfig = SOURCEGRAPH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
        ),
        primary_keys=endpoint_config.primary_keys,
        # repositories is requested with orderBy: REPOSITORY_CREATED_AT ascending; the other
        # endpoints are full-refresh only, so the watermark direction is unused for them.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
