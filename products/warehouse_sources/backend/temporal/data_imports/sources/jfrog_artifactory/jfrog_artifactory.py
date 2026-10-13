import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.settings import (
    AQL_PAGE_SIZE,
    JFROG_ARTIFACTORY_ENDPOINTS,
    XRAY_PAGE_SIZE,
    JfrogArtifactoryEndpointConfig,
)

# Artifactory's REST and AQL APIs live under /artifactory on both SaaS (<company>.jfrog.io)
# and standard self-hosted installs.
ARTIFACTORY_API_PATH = "/artifactory/api"
XRAY_API_PATH = "/xray/api"

# Xray's v1 violations search answers 429 once a query scrolls past 50,000 matching violations, so
# restart the scroll from the last seen creation time well before that depth.
XRAY_MAX_SCROLL_ROWS = 10_000

# Artifactory defaults to a 6,000-byte AQL query limit. Related-domain requests use an `$or`
# clause per parent, so split before sending rather than relying only on the response-size guard.
AQL_RELATED_QUERY_MAX_BYTES = 6_000

REQUEST_TIMEOUT_SECONDS = 120
PROBE_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# The platform URL is user-supplied, so a hostile host could stream an arbitrarily large (or
# highly compressed) body and OOM the import worker. Cap how much we buffer before decoding JSON and
# how long a single transfer may run, on both the sync path and the reachability probe. A legitimate
# response is one AQL page (AQL_PAGE_SIZE rows of small metadata) or a REST listing
# (repositories/storageinfo, bounded by repo count), i.e. a few MB at most, so keep the byte cap low.
# json.loads allocates one Python object per value, so a compact body of many small values amplifies
# far past its byte size — cap the number of structural tokens too so an amplification bomb (millions
# of `{}`/`[]`/scalars) is rejected before it is materialized, even while under the byte cap.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_JSON_TOKENS = 1_000_000
MAX_TRANSFER_SECONDS = 600
RESPONSE_CHUNK_BYTES = 256 * 1024
RESPONSE_LIMIT_ERROR = "JFrog response exceeded a transfer limit"


class JfrogArtifactoryRetryableError(Exception):
    pass


class JfrogArtifactoryResponseTooLargeError(Exception):
    # Non-retryable: a body over the cap won't shrink on retry, and buffering it again wastes the worker.
    pass


def _read_capped_body(response: requests.Response, url: str) -> bytes:
    """Stream the response body under a byte cap and a wall-clock deadline, then return the raw bytes.

    Called only when the caller opened the request with ``stream=True`` so the body isn't buffered
    until here. ``iter_content`` decodes any content-encoding, so ``total`` and the cap track the
    decoded size that actually lands in memory — a compression bomb trips the cap as it inflates.
    Raises :class:`JfrogArtifactoryResponseTooLargeError` before the JSON is decoded rather than
    letting a hostile host OOM the worker. The wall-clock deadline bounds a transfer that keeps
    yielding chunks but drags on; a per-read socket timeout (``REQUEST_TIMEOUT_SECONDS``) bounds a
    stall with no bytes at all, and a hung sync is ultimately bounded by the Temporal activity timeout.
    """
    started = time.monotonic()
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise JfrogArtifactoryResponseTooLargeError(
                f"{RESPONSE_LIMIT_ERROR}: {url} returned more than {MAX_RESPONSE_BYTES} bytes"
            )
        if time.monotonic() - started > MAX_TRANSFER_SECONDS:
            raise JfrogArtifactoryResponseTooLargeError(
                f"{RESPONSE_LIMIT_ERROR}: {url} transfer exceeded {MAX_TRANSFER_SECONDS}s"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _loads_bounded(body: bytes, url: str) -> Any:
    """Parse JSON only after bounding how many Python objects it can materialize.

    ``json.loads`` allocates a distinct object per value, so a compact body of many ``{}``/``[]`` or
    scalars (e.g. ``[0.0, 0.0, ...]``) amplifies far beyond its byte size — enough to OOM the worker
    while under the byte cap. Structural tokens (``,`` ``{`` ``[``) are an O(n) upper bound on the
    values the parse would create (over-counting occurrences inside strings only makes the guard more
    conservative), so we can reject an amplification bomb before materializing it. The bound sits well
    above a legitimate AQL page or repo/storage listing.
    """
    tokens = body.count(b",") + body.count(b"{") + body.count(b"[")
    if tokens > MAX_JSON_TOKENS:
        raise JfrogArtifactoryResponseTooLargeError(
            f"{RESPONSE_LIMIT_ERROR}: {url} returned more than {MAX_JSON_TOKENS} JSON tokens"
        )
    return json.loads(body)


@dataclasses.dataclass
class JfrogArtifactoryResumeConfig:
    # Next AQL .offset() to request. None means "start from the first page".
    next_offset: int | None = None
    # The formatted timestamp the interrupted run's AQL filter was built with, reused verbatim on
    # resume. The pipeline checkpoints the incremental watermark per batch (asc sort), so rebuilding
    # the filter from the advanced DB value would shrink the result set and misalign every offset.
    incremental_filter_value: str | None = None


def normalize_base_url(base_url: str) -> str:
    """Normalize the JFrog platform URL and reject anything that isn't plain http(s).

    Accepts a bare host (``mycompany.jfrog.io``) or a full URL, with or without a trailing
    ``/artifactory``, and returns the platform origin (no trailing slash).
    """
    base_url = base_url.strip()
    if not base_url:
        raise ValueError("JFrog platform URL is required")
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    base_url = base_url.rstrip("/")
    # Tolerate a pasted Artifactory base URL by trimming a trailing /artifactory.
    if base_url.endswith("/artifactory"):
        base_url = base_url[: -len("/artifactory")]
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid JFrog platform URL: {base_url}")
    if parsed.path:
        # Artifactory serves its API under /artifactory on the platform origin; a leftover path
        # means the input wasn't a platform URL (or tried to smuggle one past the host checks).
        raise ValueError(f"Invalid JFrog platform URL (must not contain a path): {base_url}")
    # The access token rides in the Authorization header on every request, so plaintext http would
    # leak it to any network observer. On PostHog Cloud the request egresses over the public
    # internet, so require https. Self-hosted operators control their own network path, so http
    # stays allowed there — mirroring how host IP safety is only enforced on cloud.
    if parsed.scheme == "http" and is_cloud():
        raise ValueError("JFrog platform URL must use https")
    # SSRF guard: urlparse treats a backslash as part of the path and an "@" as a userinfo
    # separator, but urllib3/requests treat the backslash as an authority separator, so
    # `http://127.0.0.1\@example.com` validates as example.com yet connects to 127.0.0.1.
    # A legitimate platform URL has no userinfo, so reject either construct outright.
    if "\\" in base_url or "%5c" in base_url.lower() or "@" in parsed.netloc:
        raise ValueError(f"Invalid JFrog platform URL: {base_url}")
    return base_url


def hostname_of(base_url: str) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


def _api_url(base_url: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}{ARTIFACTORY_API_PATH}{path}"


def _xray_url(base_url: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}{XRAY_API_PATH}{path}"


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _get_session(access_token: str) -> requests.Session:
    # `base_url` is user-supplied, so pin redirects off so validation and the outbound request
    # stay on the same target (SSRF defense-in-depth). Redact the token from logs.
    return make_tracked_session(redact_values=(access_token,), allow_redirects=False)


def _format_aql_datetime(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 string AQL date comparisons accept.

    The AQL docs use explicit UTC offsets (e.g. ``2012-07-16T19:20:30.45+01:00``), so emit
    millisecond precision with a ``+00:00`` offset rather than the ``Z`` suffix.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
    return str(value)


def build_aql_query(
    config: JfrogArtifactoryEndpointConfig,
    incremental_field: str | None = None,
    incremental_filter_value: str | None = None,
    offset: int = 0,
    limit: int = AQL_PAGE_SIZE,
) -> str:
    """Build one AQL page query, e.g. ``items.find({...}).include(...).sort(...).offset(0).limit(1000)``.

    The sort field always matches the filter field (or the endpoint default on full refresh) so
    rows arrive in ascending cursor order and offset pagination walks a stable ordering.
    """
    sort_field = (incremental_field if incremental_filter_value else None) or config.default_incremental_field
    criteria_fields = dict(config.aql_criteria)
    if incremental_filter_value:
        criteria_fields[sort_field] = {"$gt": incremental_filter_value}
    criteria = json.dumps(criteria_fields) if criteria_fields else ""
    include = ", ".join(f'"{field}"' for field in config.aql_fields)
    sort = json.dumps({"$asc": [sort_field]})
    return f"{config.aql_domain}.find({criteria}).include({include}).sort({sort}).offset({offset}).limit({limit})"


def build_related_aql_query(config: JfrogArtifactoryEndpointConfig, parents: list[dict[str, Any]]) -> str:
    """Build the unpaginated query that fetches related-domain fields for one chunk of parent rows.

    The chunk bounds the result set, so no .sort()/.offset()/.limit() is needed (AQL would ignore
    them anyway once .include() names a related domain).
    """
    criteria = {"$or": [{key: parent.get(key) for key in config.aql_key_fields} for parent in parents]}
    include = ", ".join(f'"{field}"' for field in (*config.aql_fields, *config.aql_related_fields))
    return f"{config.aql_domain}.find({json.dumps(criteria)}).include({include})"


def build_xray_violations_request(
    created_from: str | None = None, page: int = 1, limit: int = XRAY_PAGE_SIZE
) -> dict[str, Any]:
    # Xray's `offset` is a 1-based page number, not a row offset.
    return {
        "filters": {"created_from": created_from} if created_from else {},
        "pagination": {"order_by": "created", "direction": "asc", "limit": limit, "offset": page},
    }


@retry(
    retry=retry_if_exception_type(
        (
            JfrogArtifactoryRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    data: str | None = None,
) -> Any:
    # stream=True so the (user-supplied) host's body isn't buffered until we read it under a cap.
    response = session.request(method, url, headers=headers, data=data, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

    # JFrog Cloud tiers rate limit; transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise JfrogArtifactoryRetryableError(f"JFrog API error (retryable): status={response.status_code}, url={url}")

    body = _read_capped_body(response, url)

    if not response.ok:
        logger.error(f"JFrog API error: status={response.status_code}, body={body[:500]!r}, url={url}")
        response.raise_for_status()

    return _loads_bounded(body, url)


def _get_json(
    session: requests.Session, base_url: str, access_token: str, path: str, logger: FilteringBoundLogger
) -> Any:
    return _request(session, "GET", _api_url(base_url, path), _headers(access_token), logger)


def _post_aql(
    session: requests.Session, base_url: str, access_token: str, query: str, logger: FilteringBoundLogger
) -> dict[str, Any]:
    # AQL queries are POSTed as a text/plain body, not JSON.
    headers = {**_headers(access_token), "Content-Type": "text/plain"}
    return _request(session, "POST", _api_url(base_url, "/search/aql"), headers, logger, data=query)


def _post_xray(
    session: requests.Session,
    base_url: str,
    access_token: str,
    path: str,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    headers = {**_headers(access_token), "Content-Type": "application/json"}
    return _request(session, "POST", _xray_url(base_url, path), headers, logger, data=json.dumps(body))


def _strip_domain_prefix(item: dict[str, Any], domain: str) -> dict[str, Any]:
    # Builds-domain results have historically been keyed as "build.name"/"build.created" (the
    # documented legacy output) while items-domain results use bare field names. Normalize to bare
    # names so the table schema, primary keys, and incremental watermark are stable either way.
    prefix = f"{domain.rstrip('s')}."
    return {(key[len(prefix) :] if key.startswith(prefix) else key): value for key, value in item.items()}


def _related_children(node: dict[str, Any], plural: str) -> list[dict[str, Any]]:
    # Related-domain output nests under a plural key, e.g. "modules" or "build.promotions".
    for key, value in node.items():
        if isinstance(value, list) and (key == plural or key.endswith(f".{plural}")):
            return value
    return []


def _walk_related(
    node: dict[str, Any], levels: tuple[tuple[str, str], ...], row: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    plural, domain = levels[0]
    prefix = f"{domain}."
    for child in _related_children(node, plural):
        fields = {
            key.removeprefix(prefix): value for key, value in child.items() if not isinstance(value, (list, dict))
        }
        if len(levels) == 1:
            yield {**row, **fields}
        else:
            yield from _walk_related(child, levels[1:], {**row, **{f"{domain}_{k}": v for k, v in fields.items()}})


def flatten_related(config: JfrogArtifactoryEndpointConfig, item: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Emit one row per leaf related entry, carrying the parent and intermediate-level fields."""
    parent = _strip_domain_prefix(item, config.aql_domain)
    row = {f"{config.parent_field_prefix}{key}": parent.get(key) for key in config.aql_fields}
    yield from _walk_related(item, config.aql_related_path, row)


def _fetch_related(
    session: requests.Session,
    base_url: str,
    access_token: str,
    config: JfrogArtifactoryEndpointConfig,
    parents: list[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    query = build_related_aql_query(config, parents)
    if len(query.encode()) > AQL_RELATED_QUERY_MAX_BYTES and len(parents) > 1:
        middle = len(parents) // 2
        yield from _fetch_related(session, base_url, access_token, config, parents[:middle], logger)
        yield from _fetch_related(session, base_url, access_token, config, parents[middle:], logger)
        return

    try:
        data = _post_aql(session, base_url, access_token, query, logger)
    except JfrogArtifactoryResponseTooLargeError:
        # A few very large builds can push one chunk past the response cap; split until it fits.
        # Each half yields on its own so split responses never pile up in memory.
        if len(parents) <= 1:
            raise
        middle = len(parents) // 2
        yield from _fetch_related(session, base_url, access_token, config, parents[:middle], logger)
        yield from _fetch_related(session, base_url, access_token, config, parents[middle:], logger)
        return

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in data.get("results", []):
        for row in flatten_related(config, item):
            key = tuple(row.get(field) for field in config.primary_keys)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    if rows:
        yield rows


def _yield_with_checkpoint(
    rows: Iterator[list[dict[str, Any]]],
    next_state: JfrogArtifactoryResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[JfrogArtifactoryResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Hold one batch so the next-page state is staged immediately before the last yield.

    An `aql_related` page expands into zero or more related-row batches. Staging `next_state` as
    soon as the parent page is read — before any of its related rows are yielded — can commit past
    a page whose related rows are not all written yet. Staging it right after the last of those
    batches yields, the pattern the resume-state ratchet forbids, can lose that batch on a worker
    shutdown. Holding one batch back lets the state land immediately before the batch it allows a
    resume to skip, exactly when every earlier row is safe to resume past.
    """
    try:
        pending = next(rows)
    except StopIteration:
        if next_state is not None:
            resumable_source_manager.save_state(next_state)
            resumable_source_manager.safe_point()
        return

    for batch in rows:
        yield pending
        pending = batch

    if next_state is not None:
        resumable_source_manager.save_state(next_state)
    yield pending
    if next_state is not None:
        resumable_source_manager.safe_point()


def _iter_aql_pages(
    session: requests.Session,
    base_url: str,
    access_token: str,
    config: JfrogArtifactoryEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JfrogArtifactoryResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[tuple[list[dict[str, Any]], JfrogArtifactoryResumeConfig | None]]:
    """Yield each AQL page alongside the resume state for the page after it.

    The state is `None` on the last page: the generator ends right after it, and the pipeline then
    commits whatever state the caller staged for the rows it still holds. A plain `aql` endpoint can
    save and yield the state's page directly; an `aql_related` endpoint expands one page into
    several related-row batches first, so it stages the state once all of them are yielded instead.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_offset:
        offset = resume.next_offset
        filter_value = resume.incremental_filter_value
        logger.debug(f"JFrog Artifactory: resuming {config.name} from offset {offset}")
    else:
        offset = 0
        filter_value = (
            _format_aql_datetime(db_incremental_field_last_value)
            if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value
            else None
        )

    while True:
        query = build_aql_query(config, incremental_field, filter_value, offset)
        data = _post_aql(session, base_url, access_token, query, logger)
        results = data.get("results", [])
        if not results:
            break

        has_more = len(results) >= AQL_PAGE_SIZE
        next_state = (
            JfrogArtifactoryResumeConfig(next_offset=offset + len(results), incremental_filter_value=filter_value)
            if has_more
            else None
        )

        yield [_strip_domain_prefix(item, config.aql_domain) for item in results], next_state

        if not has_more:
            break
        offset += len(results)
        resumable_source_manager.safe_point()


def _xray_restart_filter(last_created: Any, current_filter: str | None) -> str | None:
    """Return a `created_from` that restarts the scroll near the last row, or None to keep paging.

    Backs off one second in case `created_from` is exclusive; the overlap re-reads a few rows,
    which merge dedupes on the primary key. Returns None when the restart wouldn't move forward
    (e.g. more than a scroll's worth of violations share one timestamp).
    """
    if not isinstance(last_created, str):
        return None
    try:
        restart = datetime.fromisoformat(last_created) - timedelta(seconds=1)
        if current_filter is not None and restart <= datetime.fromisoformat(current_filter):
            return None
    except ValueError:
        return None
    return _format_aql_datetime(restart)


def _iter_xray_violations(
    session: requests.Session,
    base_url: str,
    access_token: str,
    config: JfrogArtifactoryEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JfrogArtifactoryResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_offset:
        page = resume.next_offset
        filter_value = resume.incremental_filter_value
    else:
        page = 1
        filter_value = (
            _format_aql_datetime(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )

    while True:
        body = build_xray_violations_request(filter_value, page)
        data = _post_xray(session, base_url, access_token, config.path, body, logger)
        violations = data.get("violations") or []
        if not violations:
            break

        has_more = len(violations) >= XRAY_PAGE_SIZE
        if has_more:
            page += 1
            if (page - 1) * XRAY_PAGE_SIZE >= XRAY_MAX_SCROLL_ROWS:
                restart_filter = _xray_restart_filter(violations[-1].get("created"), filter_value)
                if restart_filter is not None:
                    filter_value, page = restart_filter, 1
            resumable_source_manager.save_state(
                JfrogArtifactoryResumeConfig(next_offset=page, incremental_filter_value=filter_value)
            )

        yield violations

        if not has_more:
            break
        resumable_source_manager.safe_point()


def get_rows(
    base_url: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JfrogArtifactoryResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = JFROG_ARTIFACTORY_ENDPOINTS[endpoint]
    session = _get_session(access_token)

    if config.kind == "rest":
        data = _get_json(session, base_url, access_token, config.path, logger)
        rows = (data.get(config.response_key) or []) if config.response_key else data
        if rows:
            yield rows
        return

    if config.kind == "xray":
        yield from _iter_xray_violations(
            session,
            base_url,
            access_token,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    # Related-domain tables expose parent fields as e.g. `build_created`; the parent query filters
    # and sorts on the bare primary-domain field.
    parent_incremental_field = incremental_field.removeprefix(config.parent_field_prefix) if incremental_field else None
    pages = _iter_aql_pages(
        session,
        base_url,
        access_token,
        config,
        logger,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
        parent_incremental_field,
    )

    if config.kind == "aql":
        for results, next_state in pages:
            if next_state is not None:
                resumable_source_manager.save_state(next_state)
            yield results
        return

    for parents, next_state in pages:
        related_batches = (
            batch
            for start in range(0, len(parents), config.aql_related_chunk_size)
            for batch in _fetch_related(
                session, base_url, access_token, config, parents[start : start + config.aql_related_chunk_size], logger
            )
        )
        yield from _yield_with_checkpoint(related_batches, next_state, resumable_source_manager)


def jfrog_artifactory_source(
    base_url: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JfrogArtifactoryResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = JFROG_ARTIFACTORY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def probe_endpoint(base_url: str, access_token: str, endpoint: str | None = None) -> tuple[bool, int | None]:
    """Cheap reachability probe for the token (``endpoint=None``) or one specific endpoint.

    Returns ``(ok, status_code)``; ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` when the platform URL is malformed so the caller can surface a precise message.
    """
    config = JFROG_ARTIFACTORY_ENDPOINTS[endpoint] if endpoint is not None else None
    session = _get_session(access_token)
    # stream=True keeps the (user-supplied) host's body off the wire until we ask for it — the probe
    # only inspects the status code, so we never read it, and closing the response frees the socket.
    try:
        if config is not None and config.kind == "xray":
            response = session.post(
                _xray_url(base_url, config.path),
                headers={**_headers(access_token), "Content-Type": "application/json"},
                data=json.dumps(build_xray_violations_request(limit=1)),
                timeout=PROBE_TIMEOUT_SECONDS,
                stream=True,
            )
        elif config is not None and config.kind in ("aql", "aql_related"):
            # AQL requires authentication and (for builds) admin/scoped-token access, so a
            # single-row query is the accurate scope probe for these endpoints.
            query = build_aql_query(config, limit=1)
            url = _api_url(base_url, "/search/aql")
            response = session.post(
                url,
                headers={**_headers(access_token), "Content-Type": "text/plain"},
                data=query,
                timeout=PROBE_TIMEOUT_SECONDS,
                stream=True,
            )
        else:
            path = config.path if config is not None else "/repositories"
            response = session.get(
                _api_url(base_url, path), headers=_headers(access_token), timeout=PROBE_TIMEOUT_SECONDS, stream=True
            )
    except ValueError:
        raise
    except Exception:
        return False, None
    try:
        return response.status_code == 200, response.status_code
    finally:
        response.close()
