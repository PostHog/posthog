import json
import time
import threading
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.settings import (
    AQL_PAGE_SIZE,
    JFROG_ARTIFACTORY_ENDPOINTS,
    JfrogArtifactoryEndpointConfig,
)

# Artifactory's REST and AQL APIs live under /artifactory on both SaaS (<company>.jfrog.io)
# and standard self-hosted installs.
ARTIFACTORY_API_PATH = "/artifactory/api"

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5

# The platform URL is user-supplied, so a hostile host could stream an arbitrarily large (or
# highly compressed) body and OOM the import worker. Cap how much we buffer before decoding JSON,
# and how long a single transfer may run, on both the sync path and the reachability probe.
MAX_RESPONSE_BYTES = 512 * 1024 * 1024
MAX_TRANSFER_SECONDS = 600
RESPONSE_CHUNK_BYTES = 1024 * 1024
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
    letting a hostile host OOM or occupy the worker.
    """
    started = time.monotonic()
    total = 0
    chunks: list[bytes] = []
    timed_out = threading.Event()

    def _abort_on_deadline() -> None:
        # A hostile host can trickle bytes just often enough to keep the socket-read timeout at bay
        # while never filling a chunk, so `iter_content` blocks and the in-loop deadline check below
        # never runs. This watchdog fires off-thread and closes the response, which unblocks the
        # pending read (it raises), enforcing the deadline independently of the blocking read.
        timed_out.set()
        response.close()

    watchdog = threading.Timer(MAX_TRANSFER_SECONDS, _abort_on_deadline)
    watchdog.start()
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if timed_out.is_set():
                raise JfrogArtifactoryResponseTooLargeError(
                    f"{RESPONSE_LIMIT_ERROR}: {url} transfer exceeded {MAX_TRANSFER_SECONDS}s"
                )
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
    except JfrogArtifactoryResponseTooLargeError:
        raise
    except Exception:
        # The watchdog closing the socket surfaces here as a transport error; translate it into the
        # deadline error rather than a retryable one, since retrying won't speed the host up.
        if timed_out.is_set():
            raise JfrogArtifactoryResponseTooLargeError(
                f"{RESPONSE_LIMIT_ERROR}: {url} transfer exceeded {MAX_TRANSFER_SECONDS}s"
            ) from None
        raise
    finally:
        watchdog.cancel()
    return b"".join(chunks)


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
    criteria = json.dumps({sort_field: {"$gt": incremental_filter_value}}) if incremental_filter_value else ""
    include = ", ".join(f'"{field}"' for field in config.aql_fields)
    sort = json.dumps({"$asc": [sort_field]})
    return f"{config.aql_domain}.find({criteria}).include({include}).sort({sort}).offset({offset}).limit({limit})"


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

    return json.loads(body)


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


def _strip_domain_prefix(item: dict[str, Any], domain: str) -> dict[str, Any]:
    # Builds-domain results have historically been keyed as "build.name"/"build.created" (the
    # documented legacy output) while items-domain results use bare field names. Normalize to bare
    # names so the table schema, primary keys, and incremental watermark are stable either way.
    prefix = f"{domain.rstrip('s')}."
    return {(key[len(prefix) :] if key.startswith(prefix) else key): value for key, value in item.items()}


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

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_offset:
        offset = resume.next_offset
        filter_value = resume.incremental_filter_value
        logger.debug(f"JFrog Artifactory: resuming {endpoint} from offset {offset}")
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
        yield [_strip_domain_prefix(item, config.aql_domain) for item in results]

        if not has_more:
            break
        offset += len(results)
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key.
        resumable_source_manager.save_state(
            JfrogArtifactoryResumeConfig(next_offset=offset, incremental_filter_value=filter_value)
        )


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
        if config is not None and config.kind == "aql":
            # AQL requires authentication and (for builds) admin/scoped-token access, so a
            # single-row query is the accurate scope probe for these endpoints.
            query = build_aql_query(config, limit=1)
            url = _api_url(base_url, "/search/aql")
            response = session.post(
                url,
                headers={**_headers(access_token), "Content-Type": "text/plain"},
                data=query,
                timeout=30,
                stream=True,
            )
        else:
            path = config.path if config is not None else "/repositories"
            response = session.get(_api_url(base_url, path), headers=_headers(access_token), timeout=30, stream=True)
    except ValueError:
        raise
    except Exception:
        return False, None
    try:
        return response.status_code == 200, response.status_code
    finally:
        response.close()
