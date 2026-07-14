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

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 6
# Langfuse rate limits are per-minute windows (as low as 15 req/min for legacy read endpoints on
# the Hobby plan), so honor Retry-After up to a full window plus slack.
MAX_RETRY_AFTER_SECONDS = 120

DEFAULT_HOST = "https://cloud.langfuse.com"
HOST_NOT_ALLOWED_ERROR = "Langfuse host is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Langfuse host must use HTTPS"


class LangfuseRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LangfuseHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class LangfuseResumeConfig:
    # Next page number ("page" endpoints) or opaque cursor ("cursor" endpoints) to fetch.
    page: int | None = None
    cursor: str | None = None
    # The from-filter value the interrupted run started with. Reused verbatim on resume so the
    # saved page/cursor stays aligned with the query it was produced by (the incremental watermark
    # can advance mid-run for ascending endpoints).
    from_value: str | None = None


def normalize_host(host: str | None) -> str:
    """Turn whatever the user typed into a bare Langfuse base URL.

    Accepts ``us.cloud.langfuse.com``, ``https://cloud.langfuse.com/``, or a self-hosted URL and
    returns it scheme-prefixed with no trailing slash. Defaults to https when no scheme is given.
    """
    host = (host or "").strip()
    if not host:
        return DEFAULT_HOST
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    return host.rstrip("/")


def _host_only(host: str | None) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _is_https(host: str | None) -> bool:
    # The secret key rides in the Authorization header (Basic auth), so refuse plaintext HTTP to
    # keep an on-path attacker from capturing it.
    return urlparse(normalize_host(host)).scheme == "https"


def _check_host(host: str | None, team_id: int) -> None:
    """Refuse plaintext or internal hosts before any credential-bearing request goes out.

    Raises LangfuseHostNotAllowedError with a message get_non_retryable_errors() matches, so the
    workflow fails fast instead of retrying an SSRF/host failure.
    """
    if not _is_https(host):
        raise LangfuseHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

    # The host is customer-controlled (self-hosted Langfuse), so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    host_ok, host_err = _is_host_safe(_host_only(host), team_id)
    if not host_ok:
        raise LangfuseHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: {host_err}" if host_err else HOST_NOT_ALLOWED_ERROR
        )


def _format_incremental_value(value: Any) -> str:
    """Langfuse timestamp filters want ISO 8601; we normalize to UTC with a literal Z."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _from_filter_value(
    config: LangfuseEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> str | None:
    """The formatted lower-bound filter value for this run, or None for a full / first sync."""
    if not (should_use_incremental_field and db_incremental_field_last_value and config.incremental_filter_param):
        return None

    field = incremental_field or config.default_incremental_field
    if field != config.default_incremental_field:
        raise ValueError(
            f"Unsupported Langfuse incremental field '{field}' for endpoint '{config.name}'. "
            f"Expected '{config.default_incremental_field}'."
        )

    value = db_incremental_field_last_value
    if config.incremental_lookback is not None and isinstance(value, datetime):
        value = value - config.incremental_lookback
    elif config.incremental_lookback is not None and isinstance(value, date):
        value = datetime.combine(value, datetime.min.time(), tzinfo=UTC) - config.incremental_lookback

    return _format_incremental_value(value)


def _build_params(config: LangfuseEndpointConfig, from_value: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}
    if from_value is not None and config.incremental_filter_param:
        params[config.incremental_filter_param] = from_value
    params.update(config.extra_params)
    return params


def _parse_retry_after(response: requests.Response) -> float | None:
    """Honor ``Retry-After`` in whole seconds on 429. Ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, LangfuseRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=2, max=60)(retry_state)


def validate_credentials(
    host: str | None, public_key: str, secret_key: str, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the project endpoint to confirm the key pair is genuine for the configured host."""
    if not public_key or not public_key.strip():
        return False, "Missing public key"
    if not secret_key or not secret_key.strip():
        return False, "Missing secret key"

    if not _host_only(host):
        return False, "Invalid Langfuse host"

    if not _is_https(host):
        return False, HTTP_NOT_ALLOWED_ERROR

    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_only(host), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{normalize_host(host)}/api/public/projects"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address (SSRF).
        response = make_tracked_session().get(
            url, auth=(public_key.strip(), secret_key.strip()), timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, (
            "The Langfuse host returned an unexpected redirect. Enter just the API base URL for your "
            "region (for example https://cloud.langfuse.com or https://us.cloud.langfuse.com) or your "
            "self-hosted instance, with no extra path."
        )

    if response.status_code == 200:
        return True, None

    if response.status_code in (401, 403):
        return False, (
            "Invalid Langfuse API keys. Check the project public key and secret key, and make sure the "
            "host matches your Langfuse data region."
        )

    try:
        body = response.json()
        return False, body.get("message", response.text)
    except Exception:
        return False, response.text


def get_rows(
    host: str | None,
    public_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangfuseResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LANGFUSE_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding).
    _check_host(host, team_id)

    from_value = _from_filter_value(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    page: int = 1
    cursor: str | None = None
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        # Reuse the interrupted run's from-filter so the saved page/cursor matches its query.
        from_value = resume_config.from_value
        page = resume_config.page or 1
        cursor = resume_config.cursor
        logger.debug(f"Langfuse: resuming {endpoint} from page={page}, cursor={cursor}")

    base_params = _build_params(config, from_value)
    url = f"{normalize_host(host)}{config.path}"
    auth = (public_key.strip(), secret_key.strip())
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()

    @retry(
        retry=retry_if_exception_type((LangfuseRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal address (SSRF).
        response = session.get(url, params=params, auth=auth, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise LangfuseRetryableError(
                f"Langfuse API error (retryable): status={response.status_code}, endpoint={endpoint}",
                retry_after=retry_after,
            )

        if response.is_redirect or response.is_permanent_redirect:
            raise LangfuseHostNotAllowedError(
                f"{HOST_NOT_ALLOWED_ERROR}: Langfuse API returned an unexpected redirect "
                f"(status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"Langfuse API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        params = dict(base_params)
        if config.pagination == "page":
            params["page"] = page
        elif cursor is not None:
            params["cursor"] = cursor

        data = fetch_page(params)
        items = data.get("data") or []
        meta = data.get("meta") or {}

        if config.pagination == "page":
            # totalPages is documented as always present; stop rather than loop if it ever isn't.
            total_pages = meta.get("totalPages")
            has_next = bool(items) and total_pages is not None and page < total_pages
            next_state = LangfuseResumeConfig(page=page + 1, from_value=from_value)
        else:
            next_cursor = meta.get("cursor")
            has_next = bool(items) and next_cursor is not None
            next_state = LangfuseResumeConfig(cursor=next_cursor, from_value=from_value)

        if items:
            yield items
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
            # page rather than skipping it — merge dedupes on the primary key.
            if has_next:
                resumable_source_manager.save_state(next_state)

        if not has_next:
            break

        if config.pagination == "page":
            page += 1
        else:
            cursor = meta.get("cursor")


def langfuse_source(
    host: str | None,
    public_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LangfuseResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = LANGFUSE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            public_key=public_key,
            secret_key=secret_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
