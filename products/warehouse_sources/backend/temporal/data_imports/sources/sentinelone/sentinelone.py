import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import (
    SENTINELONE_ENDPOINTS,
    SentinelOneEndpointConfig,
)

API_BASE_PATH = "/web/api/v2.1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

HOST_NOT_ALLOWED_ERROR = "SentinelOne console URL is not allowed"


class SentinelOneRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SentinelOneHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class SentinelOneResumeConfig:
    next_url: str


def normalize_console_url(console_url: str) -> str:
    """Turn whatever the user typed into a bare SentinelOne console host.

    Accepts values like ``usea1-example.sentinelone.net``,
    ``https://usea1-example.sentinelone.net/``, or a pasted API URL with the
    ``/web/api/v2.1`` path, and returns ``usea1-example.sentinelone.net``.
    """
    console_url = console_url.strip()
    console_url = re.sub(r"^https?://", "", console_url, flags=re.IGNORECASE)
    console_url = console_url.split("/")[0]
    return console_url.strip().rstrip("/")


def _base_url(console_url: str) -> str:
    return f"https://{normalize_console_url(console_url)}{API_BASE_PATH}"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"ApiToken {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _format_datetime_z(dt: datetime) -> str:
    """SentinelOne accepts ISO 8601 timestamps; use millisecond precision with a ``Z`` suffix."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_initial_params(
    config: SentinelOneEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}

    if config.default_incremental_field is None:
        # Full-refresh-only endpoint (groups, sites): stay on the API's default order —
        # their sortBy enums aren't verifiable without a live tenant.
        return params

    # Cursor pagination needs a deterministic ascending walk for the watermark to be
    # meaningful; sort by the field we filter on (createdAt for full refreshes, since
    # it's stable while rows are inserted mid-sync).
    sort_field = (
        (incremental_field or config.default_incremental_field) if should_use_incremental_field else "createdAt"
    )
    params["sortBy"] = sort_field
    params["sortOrder"] = "asc"

    if should_use_incremental_field and db_incremental_field_last_value:
        params[f"{sort_field}__gte"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _build_initial_url(console_url: str, config: SentinelOneEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{_base_url(console_url)}{config.path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _next_page_url(current_url: str, cursor: str) -> str:
    """Same endpoint + params as the current page, with the ``cursor`` param swapped in.

    SentinelOne's cursor is only valid for the exact query it was minted against, so every
    non-cursor param must be carried over unchanged.
    """
    parsed = urlparse(current_url)
    params = dict(parse_qsl(parsed.query))
    params["cursor"] = cursor
    return parsed._replace(query=urlencode(params)).geturl()


def _is_same_host(url: str, console_url: str) -> bool:
    """Whether ``url`` points at the configured console host.

    Resume URLs come from Redis state; pin them to the validated console host so a
    poisoned entry can't point the sync at an arbitrary internal address (SSRF).
    """
    try:
        return (urlparse(url).hostname or "").lower() == normalize_console_url(console_url).lower()
    except Exception:
        return False


def _extract_rows(payload: dict[str, Any], config: SentinelOneEndpointConfig) -> list[dict[str, Any]]:
    data = payload.get("data")
    if config.data_key is not None:
        if isinstance(data, dict) and isinstance(data.get(config.data_key), list):
            return data[config.data_key]
        return []
    return data if isinstance(data, list) else []


def _normalize_row(row: dict[str, Any], config: SentinelOneEndpointConfig) -> dict[str, Any]:
    """Hoist createdAt/updatedAt to the top level where the object nests them.

    Threats keep their timestamps under ``threatInfo``; the pipeline reads the
    incremental watermark and partition key from top-level columns.
    """
    if config.hoist_datetime_fields_from:
        nested = row.get(config.hoist_datetime_fields_from)
        if isinstance(nested, dict):
            for field in ("createdAt", "updatedAt"):
                if field not in row and nested.get(field) is not None:
                    row[field] = nested[field]
    return row


def _parse_error_message(response: requests.Response) -> str:
    """SentinelOne errors arrive as ``{"errors": [{"title": ..., "detail": ...}]}``."""
    try:
        errors = response.json().get("errors") or []
        if errors and isinstance(errors[0], dict):
            title = errors[0].get("title") or ""
            detail = errors[0].get("detail") or ""
            message = ": ".join(part for part in (title, detail) if part)
            if message:
                return message
    except Exception:
        pass
    return response.text


def validate_credentials(
    console_url: str, api_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the console to confirm the API token is genuine.

    At source-create (``schema_name is None``) we hit the cheap ``/system/info`` endpoint
    and accept 403 — the token is valid but its user's role may lack that view. A scoped
    probe (``schema_name`` set) hits the endpoint itself and treats 403 as a hard failure.
    """
    normalized = normalize_console_url(console_url)
    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid SentinelOne console URL"

    # The console host is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    endpoint_config = SENTINELONE_ENDPOINTS.get(schema_name) if schema_name else None
    if endpoint_config is not None:
        url = f"{_base_url(normalized)}{endpoint_config.path}"
        params: dict[str, Any] = {"limit": 1}
    else:
        url = f"{_base_url(normalized)}/system/info"
        params = {}

    try:
        # Don't follow redirects: the validated host could 3xx to an internal address,
        # defeating the host check above (SSRF).
        response = make_tracked_session(redact_values=(api_token,), capture=False, allow_redirects=False).get(
            url, headers=_get_headers(api_token), params=params, timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid SentinelOne API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing role/scope for this probe — let source creation through.
            return True, None
        return False, "Your SentinelOne API token's user lacks the required permissions for this endpoint"

    return False, _parse_error_message(response)


def _parse_retry_after(response: requests.Response) -> float | None:
    """Honor a whole-seconds ``Retry-After`` on 429. Ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, SentinelOneRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def get_rows(
    console_url: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SentinelOneResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = SENTINELONE_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)

    # Re-check at run time (not just at source-create) in case the console URL was edited
    # or now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_console_url(console_url), team_id)
    if not host_ok:
        raise SentinelOneHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    initial_url = _build_initial_url(console_url, config, params)
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_same_host(resume_config.next_url, console_url):
        url: str = resume_config.next_url
        logger.debug(f"SentinelOne: resuming from URL: {url}")
    else:
        if resume_config is not None:
            logger.warning("SentinelOne: ignoring resume URL whose host does not match the configured console URL")
        url = initial_url

    session = make_tracked_session(redact_values=(api_token,), capture=False, allow_redirects=False)

    @retry(
        retry=retry_if_exception_type((SentinelOneRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal
        # address, bypassing the host validation done before the request (SSRF).
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise SentinelOneRetryableError(
                f"SentinelOne API error (retryable): status={response.status_code}, url={page_url}",
                retry_after=retry_after,
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly
        # rather than silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise SentinelOneHostNotAllowedError(
                f"SentinelOne API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"SentinelOne API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        payload = fetch_page(url)

        rows = _extract_rows(payload, config)
        if not rows:
            break

        next_cursor = (payload.get("pagination") or {}).get("nextCursor")

        yield [_normalize_row(row, config) for row in rows]

        if not next_cursor:
            break

        # Save AFTER yielding so a crash re-yields the last page instead of skipping it —
        # merge dedupes the re-yielded rows on the primary key.
        next_url = _next_page_url(url, next_cursor)
        resumable_source_manager.save_state(SentinelOneResumeConfig(next_url=next_url))
        url = next_url


def sentinelone_source(
    console_url: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SentinelOneResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SENTINELONE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            console_url=console_url,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        # Incremental-capable endpoints request sortBy=<cursor field>&sortOrder=asc, so
        # ascending order is explicit rather than assumed from the API default.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
