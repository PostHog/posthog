import re
import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.settings import (
    FORMBRICKS_ENDPOINTS,
    FormbricksEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# v2 list endpoints accept a limit of 1-250; the largest page minimises round trips.
PAGE_SIZE = 250
# The host is customer-controlled, so a malicious or misconfigured server could stream an
# unbounded body and exhaust a shared worker (requests buffers the whole body into memory by
# default, and the read timeout only guards idle gaps, not a steady large transfer). Cap what we
# read into memory. Generous enough for a full v1 collection page; anything past it is refused.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 256 * 1024
# Wall-clock budget for downloading one page's body. requests' timeout only bounds each individual
# socket read, so a host that dribbles the body slowly could hold the connection (and a shared
# worker) open far longer than any read timeout while staying under MAX_RESPONSE_BYTES. This caps
# total transfer time — 256 MiB in 300s is a ~0.85 MiB/s floor, far below any real API response and
# far above a slow-drip stall.
MAX_DOWNLOAD_SECONDS = 300

DEFAULT_HOST = "https://app.formbricks.com"
HOST_NOT_ALLOWED_ERROR = "Formbricks host is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Formbricks host must use HTTPS"
RESPONSE_TOO_LARGE_ERROR = "Formbricks response body was too large"
RESPONSE_TOO_SLOW_ERROR = "Formbricks response download was too slow"
# Cheap probe returning the environment/project the API key is scoped to.
DEFAULT_PROBE_PATH = "/api/v1/management/me"


class FormbricksRetryableError(Exception):
    pass


class FormbricksHostNotAllowedError(Exception):
    pass


class FormbricksResponseTooLargeError(Exception):
    pass


class FormbricksResponseTooSlowError(Exception):
    pass


def _read_capped_body(response: requests.Response) -> bytes:
    """Stream the body into memory, aborting past MAX_RESPONSE_BYTES or MAX_DOWNLOAD_SECONDS.

    The host is customer-controlled, so a body must never be buffered unbounded (size cap) nor be
    allowed to hold the connection open indefinitely by dribbling under the per-read timeout (time
    cap). Both are non-retryable: re-fetching the same page yields the same oversized/slow body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise FormbricksResponseTooSlowError(
                    f"{RESPONSE_TOO_SLOW_ERROR}: exceeded {MAX_DOWNLOAD_SECONDS}s download budget"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise FormbricksResponseTooLargeError(
                    f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {MAX_RESPONSE_BYTES} bytes"
                )
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


@dataclasses.dataclass
class FormbricksResumeConfig:
    # Full URL of the next page to fetch. limit/skip and any incremental window params are baked
    # into the URL, so a crashed sync resumes the exact request sequence it was running; merge
    # dedupes the re-pulled page on the primary key.
    next_url: str


def normalize_host(host: str | None) -> str:
    """Turn whatever the user typed into a bare Formbricks base URL.

    Accepts ``app.formbricks.com``, ``https://formbricks.example.com/``, or
    ``https://formbricks.example.com/api`` and returns ``https://formbricks.example.com``.
    Defaults to https when no scheme is given, and to Formbricks Cloud when empty.
    """
    host = (host or "").strip()
    if not host:
        return DEFAULT_HOST
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    host = host.rstrip("/")
    host = re.sub(r"/api(/v[12])?$", "", host, flags=re.IGNORECASE)
    return host.rstrip("/")


def _host_only(host: str | None) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _is_https(host: str | None) -> bool:
    # The API key rides in the x-api-key header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(normalize_host(host)).scheme == "https"


def _is_same_host(url: str, host: str | None) -> bool:
    """Whether ``url`` points at the configured Formbricks host over HTTPS.

    Resume URLs come from Redis and could otherwise be replayed against a different host after the
    source's host field is edited, so we pin them to the validated host before sending the API key.
    """
    try:
        parsed = urlparse(url)
        configured = urlparse(normalize_host(host))
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == (configured.hostname or "").lower()
            and (parsed.port or 443) == (configured.port or 443)
        )
    except Exception:
        return False


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Formbricks date filters want ISO 8601; we normalize to UTC with a literal Z."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_initial_params(
    config: FormbricksEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    if not config.paginated:
        # v1 list endpoints return the whole collection and document no query params.
        return {}

    params: dict[str, Any] = {"limit": PAGE_SIZE, "skip": 0}
    sort_field = "createdAt"

    if should_use_incremental_field and db_incremental_field_last_value is not None and config.incremental_fields:
        field_name = incremental_field or config.default_incremental_field or "createdAt"
        allowed = {f["field"] for f in config.incremental_fields}
        if field_name not in allowed:
            raise ValueError(
                f"Unsupported Formbricks incremental field '{field_name}' for endpoint '{config.name}'. "
                f"Expected one of: {sorted(allowed)}."
            )
        params["startDate"] = _format_incremental_value(db_incremental_field_last_value)
        params["filterDateField"] = field_name
        sort_field = field_name

    # Ascending sort on the filter field keeps skip-based pages stable while rows are inserted
    # mid-sync and lets the pipeline checkpoint the incremental watermark after every batch. Only
    # sent to endpoints that document sortBy/order, so a strict validator can't 400 on the others.
    if config.supports_sort:
        params["sortBy"] = sort_field
        params["order"] = "asc"
    return params


def _build_url(host: str | None, path: str, params: dict[str, Any]) -> str:
    url = f"{normalize_host(host)}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _advance_skip(url: str) -> str:
    """Return ``url`` with its ``skip`` offset advanced by one page."""
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query))
    limit = int(params.get("limit", PAGE_SIZE))
    params["skip"] = str(int(params.get("skip", 0)) + limit)
    return parsed._replace(query=urlencode(params)).geturl()


@retry(
    retry=retry_if_exception_type((FormbricksRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    # Don't follow redirects: a customer-controlled host could 3xx at an internal address (SSRF).
    # stream=True so the body isn't buffered until we cap it — see _read_capped_body.
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True)

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise FormbricksRetryableError(f"Formbricks API error (retryable): status={response.status_code}, url={url}")

    if response.is_redirect or response.is_permanent_redirect:
        response.close()
        raise FormbricksHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: Formbricks API returned an unexpected redirect "
            f"(status={response.status_code}); refusing to follow it"
        )

    body = _read_capped_body(response)

    if not response.ok:
        logger.error(
            f"Formbricks API error: status={response.status_code}, body={body.decode(errors='replace')}, url={url}"
        )
        response.raise_for_status()

    try:
        data = json.loads(body or b"null")
    except ValueError:
        raise FormbricksRetryableError(f"Formbricks returned a non-JSON payload for {url}")  # noqa: B904
    # Both v1 and v2 management endpoints wrap rows in {"data": [...]}.
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise FormbricksRetryableError(f"Formbricks returned an unexpected payload for {url}: {type(data).__name__}")

    return data["data"]


def get_rows(
    host: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FormbricksResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FORMBRICKS_ENDPOINTS[endpoint]

    # The API key rides in a header, so refuse plaintext HTTP at run time too in case the host was
    # edited after source creation. Non-retryable — see get_non_retryable_errors().
    if not _is_https(host):
        raise FormbricksHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

    # Re-check at run time (not just at source-create) in case the host was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_only(host), team_id)
    if not host_ok:
        raise FormbricksHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: {host_err}" if host_err else HOST_NOT_ALLOWED_ERROR
        )

    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    url = _build_url(host, config.path, params)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and _is_same_host(resume.next_url, host):
        url = resume.next_url
        logger.debug(f"Formbricks: resuming {endpoint} from URL {url}")
    elif resume is not None:
        logger.warning("Formbricks: ignoring resume URL whose host does not match the configured host")

    if not config.paginated:
        items = _fetch_page(session, url, logger)
        if items:
            yield items
        return

    while True:
        items = _fetch_page(session, url, logger)
        if items:
            yield items

        # A short (or empty) page means we've reached the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        next_url = _advance_skip(url)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(FormbricksResumeConfig(next_url=next_url))
        url = next_url


def formbricks_source(
    host: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FormbricksResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = FORMBRICKS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(host: str | None, api_key: str, team_id: Optional[int] = None) -> tuple[int, Optional[str]]:
    """Probe the `me` endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection or host problem, other HTTP status otherwise.
    """
    if not _is_https(host):
        return 0, HTTP_NOT_ALLOWED_ERROR

    # The host is customer-controlled (self-hosted Formbricks), so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_only(host), team_id)
        if not host_ok:
            return 0, host_err or HOST_NOT_ALLOWED_ERROR

    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        # stream=True so a customer-controlled host can't force us to buffer an unbounded probe
        # body: we only ever inspect the status line here, never the body.
        response = session.get(
            f"{normalize_host(host)}{DEFAULT_PROBE_PATH}", timeout=15, allow_redirects=False, stream=True
        )
    except Exception as e:
        return 0, f"Could not connect to Formbricks: {e}"

    try:
        if response.is_redirect or response.is_permanent_redirect:
            return 0, (
                "The Formbricks instance URL returned an unexpected redirect. Enter just your instance URL "
                "(for example https://app.formbricks.com or https://formbricks.example.com) and make sure it "
                "points directly at Formbricks rather than a login or proxy page."
            )

        if response.status_code in (401, 403):
            return response.status_code, None

        if not response.ok:
            return response.status_code, f"Formbricks returned HTTP {response.status_code}"

        return 200, None
    finally:
        response.close()


def validate_credentials(host: str | None, api_key: str, team_id: Optional[int] = None) -> tuple[bool, str | None]:
    if not api_key:
        return False, "Missing Formbricks API key"

    status, message = check_access(host, api_key, team_id)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Formbricks API key"
    return False, message or "Could not validate Formbricks API key"
