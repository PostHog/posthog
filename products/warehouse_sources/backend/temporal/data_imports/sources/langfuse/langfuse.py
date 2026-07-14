"""Langfuse transport layer.

Langfuse is an open-source LLM observability platform (tracing, evals, prompt management)
offered as regional cloud deployments (EU ``https://cloud.langfuse.com``, US
``https://us.cloud.langfuse.com``, plus JP/HIPAA) and self-hosted, so the API host must be
configurable. Auth is HTTP Basic with the project public key as username and secret key as
password. Every list endpoint wraps rows under ``data`` alongside a ``meta`` object; legacy
endpoints paginate by page number (``meta.totalPages``), the v2 observations and v3 scores
endpoints use an opaque cursor returned in ``meta.cursor``.

Incremental sync uses the documented server-side creation/start-time filters
(``fromTimestamp`` / ``fromStartTime``). Those filter on creation time, not updated-at, so
schemas declare a trailing lookback window (see settings.py) to re-read late-arriving
updates. Filter behavior is taken from the published OpenAPI spec; it could not be
smoke-tested against a live project without credentials.
"""

import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import (
    LANGFUSE_ENDPOINTS,
    LangfuseEndpointConfig,
)

DEFAULT_API_HOST = "https://cloud.langfuse.com"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Langfuse's legacy read APIs allow as few as 15 requests/minute on the Hobby plan, so a
# rate-limit reset can be up to a full minute away.
MAX_RETRY_AFTER_SECONDS = 60

HOST_NOT_ALLOWED_ERROR = "Langfuse host is not allowed"


class LangfuseRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LangfuseHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class LangfuseResumeConfig:
    # Position to resume from — exactly one is set depending on the endpoint's pagination
    # style. Persisted after each page is yielded, so a crash before the write re-yields the
    # last page (merge dedupes on the primary key).
    next_page: int | None = None
    next_cursor: str | None = None
    # The incremental window start (`fromTimestamp`/`fromStartTime` value) the interrupted
    # run used. Reused verbatim on resume: the DB watermark advances as batches land, so
    # rebuilding the filter from it would shift page/cursor positions and skip rows.
    incremental_from: str | None = None


def normalize_host(host: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>`` base URL.

    Blank → Langfuse Cloud (EU). Accepts bare hosts (``us.cloud.langfuse.com``) and full
    URLs with or without a scheme; trailing slashes and pasted ``/api/public`` suffixes are
    stripped.
    """
    raw = (host or "").strip()
    if not raw:
        raw = DEFAULT_API_HOST
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    return re.sub(r"/api(/public)?$", "", raw)


def _host_of(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def _format_incremental_value(value: Any) -> str:
    """Format an incremental watermark as ISO 8601 UTC with a Z suffix."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def validate_credentials(
    host: Optional[str],
    public_key: str,
    secret_key: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Probe the cheap ``/api/public/projects`` endpoint to confirm the key pair is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the keys are valid but may
    lack permission for this particular probe. A scoped probe (``schema_name`` set) treats
    403 as a hard failure.
    """
    base_url = normalize_host(host)
    hostname = _host_of(base_url)

    if not hostname:
        return False, "Invalid Langfuse host"

    # The host is fully customer-controlled for self-hosted deployments, so block hosts that
    # resolve to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    try:
        # Don't follow redirects: the validated host could 3xx to an internal address,
        # defeating the host check above (SSRF).
        response = make_tracked_session().get(
            f"{base_url}/api/public/projects",
            auth=(public_key, secret_key),
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Langfuse public/secret key pair. Confirm the keys and the region host match."

    if response.status_code == 403:
        if schema_name is None:
            # Valid keys, missing permission for this probe — let source creation through.
            return True, None
        return False, "Langfuse API keys lack the required permissions for this endpoint"

    try:
        body = response.json()
        return False, body.get("message", response.text)
    except Exception:
        return False, response.text


def _parse_retry_after(response: requests.Response) -> float | None:
    """Honor a whole-second ``Retry-After`` on 429. HTTP-date forms are ignored."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Use a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, LangfuseRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def get_rows(
    host: Optional[str],
    public_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangfuseResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config: LangfuseEndpointConfig = LANGFUSE_ENDPOINTS[endpoint]
    base_url = normalize_host(host)
    hostname = _host_of(base_url)

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise LangfuseHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    incremental_from: str | None = None
    if should_use_incremental_field and config.incremental_param and db_incremental_field_last_value is not None:
        incremental_from = _format_incremental_value(db_incremental_field_last_value)

    page: int | None = 1 if config.pagination == "page" else None
    cursor: str | None = None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        page = (resume_config.next_page or 1) if config.pagination == "page" else None
        cursor = resume_config.next_cursor
        if resume_config.incremental_from is not None:
            incremental_from = resume_config.incremental_from
        logger.debug(f"Langfuse: resuming {endpoint} from page={page}, cursor={cursor}")

    base_params: dict[str, Any] = {"limit": config.page_size, **config.extra_params}
    if incremental_from is not None and config.incremental_param:
        base_params[config.incremental_param] = incremental_from

    request_url = f"{base_url}{config.path}"
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()

    @retry(
        retry=retry_if_exception_type((LangfuseRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> requests.Response:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal
        # address, bypassing the host validation done before the request (SSRF).
        response = session.get(
            request_url,
            params=params,
            auth=(public_key, secret_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise LangfuseRetryableError(
                f"Langfuse API error (retryable): status={response.status_code}, url={request_url}",
                retry_after=retry_after,
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather
        # than silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise LangfuseHostNotAllowedError(
                f"Langfuse API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"Langfuse API error: status={response.status_code}, body={response.text}, url={request_url}")
            response.raise_for_status()

        return response

    while True:
        params = dict(base_params)
        if config.pagination == "page":
            params["page"] = page
        elif cursor is not None:
            params["cursor"] = cursor

        response = fetch_page(params)
        body = response.json()
        rows = body.get("data") or []
        if not isinstance(rows, list) or not rows:
            break

        yield rows

        meta = body.get("meta") or {}
        if config.pagination == "page":
            total_pages = meta.get("totalPages")
            assert page is not None
            if total_pages is not None and page >= int(total_pages):
                break
            page += 1
            # Checkpoint AFTER yielding: a crash before this write re-yields the page on
            # resume and merge dedupes it — never skips a page.
            resumable_source_manager.save_state(LangfuseResumeConfig(next_page=page, incremental_from=incremental_from))
        else:
            cursor = meta.get("cursor")
            if not cursor:
                break
            resumable_source_manager.save_state(
                LangfuseResumeConfig(next_cursor=cursor, incremental_from=incremental_from)
            )


def langfuse_source(
    host: Optional[str],
    public_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangfuseResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = LANGFUSE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host,
            public_key,
            secret_key,
            endpoint,
            logger,
            resumable_source_manager,
            team_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
