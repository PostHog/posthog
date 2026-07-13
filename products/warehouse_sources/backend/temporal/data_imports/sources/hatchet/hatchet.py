import re
import json
import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.settings import (
    FULL_REFRESH_SINCE_DAYS,
    HATCHET_ENDPOINTS,
    HatchetEndpointConfig,
)

# Hatchet Cloud's API host. Self-hosted users override it, but the token also embeds a `server_url`
# claim we prefer when the user leaves the host blank.
DEFAULT_HATCHET_HOST = "https://cloud.onhatchet.run"

# Returned when the resolved host resolves to a private/internal address on cloud (SSRF guard).
HOST_NOT_ALLOWED_ERROR = "Hatchet host is not allowed"

# Returned when a cloud connection would send the bearer token over plaintext HTTP.
INSECURE_SCHEME_ERROR = "Hatchet host must use https"


class HatchetRetryableError(Exception):
    pass


class HatchetHostNotAllowedError(Exception):
    """The resolved host is blocked (SSRF guard) or tried to redirect the authenticated request."""

    pass


class HatchetTokenError(ValueError):
    """The API token could not be decoded, or is missing the tenant / server URL claims we need."""


@dataclasses.dataclass
class HatchetResumeConfig:
    # Offset to resume paginating from. The `since` used when the sync started is pinned here so a
    # resumed run keeps paging the same time window (a different `since` would shift what each
    # offset points at).
    offset: int
    since: str | None = None


@dataclasses.dataclass(frozen=True)
class HatchetConnection:
    base_url: str
    tenant_id: str


def _decode_token_claims(token: str) -> dict[str, Any]:
    """Decode the (unverified) claims from a Hatchet API token. Hatchet tokens are standard 3-part
    JWTs whose payload carries `sub` (the tenant id) and `server_url`; the SDKs read them the same
    way. We only read claims, never trust them for auth, so skipping signature verification is safe."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HatchetTokenError("Invalid Hatchet API token format")
    payload = parts[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)  # restore base64 padding the JWT stripped
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, TypeError) as e:
        raise HatchetTokenError("Could not decode the Hatchet API token") from e


def _normalize_origin(raw: str) -> str:
    """Reduce a host or URL to a clean `scheme://host[:port]` origin.

    Any path, query, or fragment is dropped so a crafted host value can't extend or retarget the
    fixed Hatchet API path. A bare host gains an https scheme; an explicit http/https scheme is
    preserved (self-hosted instances may run plaintext on a private network)."""
    raw = raw.strip()
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    scheme = scheme if scheme in ("http", "https") else "https"
    return f"{scheme}://{parsed.netloc}"


def _host_from_url(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def _is_scheme_safe(base_url: str) -> tuple[bool, str | None]:
    """On cloud, refuse to send the bearer token over plaintext HTTP.

    Self-hosted PostHog may reach a private Hatchet instance over http on a trusted network, so — as
    with the SSRF host check — this is only enforced on cloud, where a plaintext origin would leak
    the token in transit."""
    if urlparse(base_url).scheme == "https" or not is_cloud():
        return True, None
    return False, INSECURE_SCHEME_ERROR


def resolve_connection(api_token: str, host: str | None = None, tenant_id: str | None = None) -> HatchetConnection:
    """Resolve the base URL and tenant id for the API calls.

    Both can be supplied explicitly (self-hosted overrides), otherwise they are read from the
    token's `server_url` / `sub` claims. The explicit host still falls back to the Cloud default so
    a token without a `server_url` claim keeps working. The resolved host — from the field or the
    claim — is normalized to a clean origin; callers still SSRF-check it before sending the token."""
    claims = _decode_token_claims(api_token)

    resolved_host = _normalize_origin(host or claims.get("server_url") or DEFAULT_HATCHET_HOST)
    resolved_tenant = (tenant_id or claims.get("sub") or "").strip()

    if not resolved_tenant:
        raise HatchetTokenError(
            "Could not determine the Hatchet tenant id from the token. Enter it manually in the tenant id field."
        )

    return HatchetConnection(base_url=resolved_host, tenant_id=resolved_tenant)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 timestamp with a `Z` suffix (what Hatchet expects)."""
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


def _resolve_since(
    config: HatchetEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> datetime | None:
    """Compute the `since` timestamp to send.

    - Incremental run with a watermark: the watermark, shifted back by the lookback overlap and
      capped at now (a future-dated cursor would make the API return nothing).
    - First incremental run (no watermark): floored to `default_lookback_days` so the backfill is
      bounded instead of crawling the whole retention window.
    - Full refresh (or `since` required but no incremental): a fixed far-past floor so we pull
      everything still retained.
    """
    now = datetime.now(UTC)

    if should_use_incremental_field and db_incremental_field_last_value:
        watermark = _to_datetime(db_incremental_field_last_value) or now
        watermark = min(watermark, now)
        if config.incremental_lookback:
            watermark = watermark - config.incremental_lookback
        return watermark

    if should_use_incremental_field and config.default_lookback_days:
        return now - timedelta(days=config.default_lookback_days)

    if config.requires_since:
        return now - timedelta(days=FULL_REFRESH_SINCE_DAYS)

    return None


def _build_initial_params(
    config: HatchetEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)
    if config.page_size:
        params["limit"] = config.page_size

    if config.supports_time_window:
        since = _resolve_since(config, should_use_incremental_field, db_incremental_field_last_value)
        if since is not None:
            params["since"] = _format_datetime(since)

    return params


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    url = f"{base_url}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            HatchetRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=60)

    # 429 and transient 5xx are retryable; auth/permission errors below are not.
    if response.status_code == 429 or response.status_code >= 500:
        raise HatchetRetryableError(f"Hatchet API error (retryable): status={response.status_code}, url={url}")

    # Redirects are disabled as an SSRF boundary; a 3xx means the host tried to bounce the
    # authenticated request elsewhere, so fail instead of parsing (or following) it.
    if 300 <= response.status_code < 400:
        raise HatchetHostNotAllowedError(
            f"Hatchet API returned an unexpected redirect: status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Hatchet API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(
    api_token: str, host: str | None, tenant_id: str | None, team_id: int | None = None
) -> tuple[bool, str | None]:
    """Probe the token by listing event keys — the cheapest tenant-scoped read with no required
    filters. A 200 confirms the token is genuine and scoped to the tenant."""
    try:
        connection = resolve_connection(api_token, host, tenant_id)
    except HatchetTokenError as e:
        return False, str(e)

    # The host (from the `host` field or the token's `server_url` claim) is user-controlled and the
    # bearer token is sent to it, so block hosts that resolve to private/internal addresses (SSRF).
    # Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_from_url(connection.base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

        scheme_ok, scheme_err = _is_scheme_safe(connection.base_url)
        if not scheme_ok:
            return False, scheme_err or INSECURE_SCHEME_ERROR

    url = f"{connection.base_url}/api/v1/stable/tenants/{connection.tenant_id}/events/keys"
    try:
        # Redact the token, never follow a redirect off the validated host, and keep the response
        # out of HTTP sample capture — Hatchet payloads can carry opaque secrets the name-based
        # scrubber won't recognise (all defense-in-depth alongside the host check above).
        response = make_tracked_session(redact_values=(api_token,), allow_redirects=False, capture=False).get(
            url, headers=_get_headers(api_token), timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid or expired Hatchet API token"
    if response.status_code == 403:
        return False, "This Hatchet API token does not have access to the tenant"
    if response.status_code == 404:
        return False, "Hatchet tenant not found. Check the tenant id and host."
    return False, f"Hatchet API returned status {response.status_code}"


def _normalize_row(item: Any) -> dict[str, Any]:
    """Flatten the resource envelope into a flat row.

    Standard resources carry a nested `metadata` object (id, createdAt, updatedAt); we lift those to
    top-level `id` / `created_at` / `updated_at` so the primary key, partition, and incremental
    cursor resolve against real columns. Event keys come back as bare strings, wrapped into a single
    `key` column."""
    if isinstance(item, str):
        return {"key": item}

    if isinstance(item, dict) and isinstance(item.get("metadata"), dict):
        metadata = item.pop("metadata")
        item["id"] = metadata.get("id")
        item["created_at"] = metadata.get("createdAt")
        item["updated_at"] = metadata.get("updatedAt")

    return item


def get_rows(
    api_token: str,
    connection: HatchetConnection,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HatchetResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = HATCHET_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)

    # Re-check at run time (not just at source-create): the host could have been edited or now
    # resolve to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_from_url(connection.base_url), team_id)
    if not host_ok:
        raise HatchetHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    # Never send the bearer token over plaintext HTTP on cloud (see _is_scheme_safe).
    scheme_ok, scheme_err = _is_scheme_safe(connection.base_url)
    if not scheme_ok:
        raise HatchetHostNotAllowedError(scheme_err or INSECURE_SCHEME_ERROR)

    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # Redact the token and never follow a redirect off the validated host. Keep response bodies out
    # of HTTP sample capture — workflow inputs/outputs and event payloads are opaque and can carry
    # secrets the name-based scrubber won't recognise.
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False, capture=False)

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)
    path = config.path.format(tenant=connection.tenant_id)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        offset = resume.offset
        # Keep paging the same window the interrupted run started on.
        if resume.since is not None:
            params["since"] = resume.since
        logger.debug(f"Hatchet: resuming {endpoint} from offset={offset}")
    else:
        offset = 0

    # The window actually in use (after any resume override); re-saved state pins this same window.
    effective_since = params.get("since")

    while True:
        # Checkpoint the offset of the page we're about to read. The batcher accumulates across
        # pages and only flushes at its size threshold, so on resume we re-read from this page and
        # let the delta merge dedupe on the primary key rather than risk skipping un-yielded rows.
        page_offset = offset
        page_params = {**params, "offset": page_offset}
        url = _build_url(connection.base_url, path, page_params)
        data = _fetch_page(session, url, headers, logger)

        # List endpoints wrap results as `{"rows": [...]}`, but some (e.g. event keys) return a bare
        # top-level array; take that directly so those endpoints don't silently sync zero rows.
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get(config.response_data_path, [])
        else:
            rows = []
        if not isinstance(rows, list) or not rows:
            break

        # A short page is the last page; a full page can still be the last if pagination says so.
        is_last_page = len(rows) < config.page_size
        pagination = data.get("pagination") if isinstance(data, dict) else None
        if not is_last_page and isinstance(pagination, dict):
            current_page = pagination.get("current_page")
            num_pages = pagination.get("num_pages")
            if isinstance(current_page, int) and isinstance(num_pages, int) and current_page >= num_pages:
                is_last_page = True

        for item in rows:
            batcher.batch(_normalize_row(item))
            if batcher.should_yield():
                yield batcher.get_table()
                # Save state AFTER yielding so a crash re-reads this page rather than skipping it.
                if not is_last_page:
                    resumable_source_manager.save_state(HatchetResumeConfig(offset=page_offset, since=effective_since))

        if is_last_page:
            break
        offset = page_offset + config.page_size

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def hatchet_source(
    api_token: str,
    connection: HatchetConnection,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HatchetResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HATCHET_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            connection=connection,
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
