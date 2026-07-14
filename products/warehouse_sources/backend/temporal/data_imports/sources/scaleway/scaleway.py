import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import (
    AUDIT_TRAIL_REGIONS,
    INSTANCE_ZONES,
    PAGE_SIZE,
    SCALEWAY_ENDPOINTS,
    ScalewayEndpointConfig,
)

BASE_URL = "https://api.scaleway.com"
REQUEST_TIMEOUT = 60

# Sentinel scope for endpoints that aren't region/zone-scoped, so the fan-out loop always iterates a
# non-empty list of exactly one pass.
_UNSCOPED = "_"


@dataclasses.dataclass
class ScalewayResumeConfig:
    # Index into the endpoint's scope list (regions/zones) currently being processed. The scope list
    # is static, so a positional index is a stable bookmark across a crash + retry. Stays 0 for
    # unscoped endpoints.
    scope_index: int = 0
    # Page-number cursor for the `page`/`page_size` and `page`/`per_page` dialects: the next page to
    # fetch within the current scope.
    page: int | None = None
    # Opaque cursor for the token dialect (Audit Trail): the next `page_token` to fetch.
    page_token: str | None = None


def _get_headers(secret_key: str) -> dict[str, str]:
    # Scaleway authenticates every request with the API secret key in the X-Auth-Token header.
    return {"X-Auth-Token": secret_key, "Accept": "application/json"}


def _format_rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scopes_for(config: ScalewayEndpointConfig) -> list[str]:
    if config.scope == "region":
        return AUDIT_TRAIL_REGIONS
    if config.scope == "zone":
        return INSTANCE_ZONES
    return [_UNSCOPED]


def _resolve_path(config: ScalewayEndpointConfig, scope: str) -> str:
    if config.scope == "region":
        return config.path.format(region=scope)
    if config.scope == "zone":
        return config.path.format(zone=scope)
    return config.path


def _base_params(config: ScalewayEndpointConfig, organization_id: str) -> dict[str, Any]:
    """Query params shared by every request for an endpoint (before the per-page cursor is added)."""
    params: dict[str, Any] = {}
    if config.pagination == "per_page":
        params["per_page"] = PAGE_SIZE
    else:
        params["page_size"] = PAGE_SIZE

    if config.org_param and organization_id:
        params[config.org_param] = organization_id
    if config.order_param and config.order_value:
        params[config.order_param] = config.order_value
    if config.lookback_param and config.lookback_days:
        params[config.lookback_param] = _format_rfc3339(datetime.now(UTC) - timedelta(days=config.lookback_days))

    params.update(config.extra_params)
    return params


def _fetch(session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger) -> dict:
    # The tracked session already retries 429 and transient 5xx (urllib3 Retry), so a non-ok response
    # here is a terminal status (401/403/404/400) — log and raise so get_non_retryable_errors can
    # classify auth/permission failures.
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    if not response.ok:
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Scaleway API error: status={response.status_code}, url={url}, body={response.text[:500]}")
        response.raise_for_status()
    return response.json()


def _iter_pages(
    session: requests.Session,
    url: str,
    base_params: dict[str, Any],
    config: ScalewayEndpointConfig,
    logger: FilteringBoundLogger,
    start_page: int | None,
    start_token: str | None,
) -> Iterator[tuple[list[dict], bool, dict[str, Any]]]:
    """Page through one scope, yielding ``(items, has_more, next_cursor)`` per response.

    ``next_cursor`` is the resume-state fragment (``{"page": n}`` or ``{"page_token": t}``) pointing at
    the page after the one just yielded; the caller persists it after handing the batch downstream.
    """
    if config.pagination == "token":
        token = start_token
        while True:
            # A page_token carries the original window/order server-side, so subsequent requests must
            # send only the token (plus page size) — re-sending the time filter alongside it can be
            # rejected or shift the window.
            if token:
                params = {"page_size": PAGE_SIZE, "page_token": token}
            else:
                params = {**base_params}
            data = _fetch(session, url, params, logger)
            items = data.get(config.data_key) or []
            next_token = data.get("next_page_token") or None
            has_more = next_token is not None
            yield items, has_more, {"page_token": next_token}
            if not has_more:
                break
            token = next_token
    else:
        page = start_page or 1
        while True:
            params = {**base_params, "page": page}
            data = _fetch(session, url, params, logger)
            items = data.get(config.data_key) or []
            # No total_count is trusted across all three dialects; a short page marks the end.
            has_more = len(items) >= PAGE_SIZE
            yield items, has_more, {"page": page + 1}
            if not has_more:
                break
            page += 1


def get_rows(
    secret_key: str,
    organization_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ScalewayResumeConfig],
) -> Iterator[list[dict]]:
    config = SCALEWAY_ENDPOINTS[endpoint]
    # One session reused across every page (and, for fan-out, every scope) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. redact_values masks the secret key in
    # logs and sample capture wherever it might appear.
    session = make_tracked_session(headers=_get_headers(secret_key), redact_values=(secret_key,))
    base_params = _base_params(config, organization_id)
    scopes = _scopes_for(config)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.scope_index if resume is not None else 0
    if start_index >= len(scopes):
        return

    for scope_index in range(start_index, len(scopes)):
        scope = scopes[scope_index]
        url = f"{BASE_URL}{_resolve_path(config, scope)}"
        # Only the scope we resumed into consumes the saved page/token cursor; later scopes start fresh.
        if resume is not None and scope_index == start_index:
            start_page = resume.page
            start_token = resume.page_token
        else:
            start_page = None
            start_token = None

        for items, has_more, next_cursor in _iter_pages(
            session, url, base_params, config, logger, start_page, start_token
        ):
            if items:
                yield items
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it (merge
            # dedupes on the primary key). Only persist when more pages remain in this scope.
            if has_more:
                resumable_source_manager.save_state(ScalewayResumeConfig(scope_index=scope_index, **next_cursor))

        # Advance the bookmark to the next scope so a crash between scopes resumes correctly.
        if scope_index + 1 < len(scopes):
            resumable_source_manager.save_state(ScalewayResumeConfig(scope_index=scope_index + 1))


def scaleway_source(
    secret_key: str,
    organization_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ScalewayResumeConfig],
) -> SourceResponse:
    config = SCALEWAY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            secret_key=secret_key,
            organization_id=organization_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Every endpoint is full refresh; sort is only for stable pagination. Requests ask for the
        # configured ascending order where the API supports it.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def probe_endpoint(secret_key: str, organization_id: str, endpoint: str) -> int:
    """Issue a minimal one-row request against an endpoint and return the HTTP status code.

    Returns 0 for a network-level failure so the caller can treat it as "not a definitive auth
    denial" rather than a missing scope.
    """
    config = SCALEWAY_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_get_headers(secret_key), redact_values=(secret_key,))
    scope = _scopes_for(config)[0]
    url = f"{BASE_URL}{_resolve_path(config, scope)}"
    params = _base_params(config, organization_id)
    if config.pagination == "per_page":
        params["per_page"] = 1
    else:
        params["page_size"] = 1
    if config.pagination != "token":
        params["page"] = 1
    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        return response.status_code
    except requests.RequestException:
        return 0


def validate_credentials(secret_key: str, organization_id: str) -> int:
    """Probe the cheapest organization-scoped endpoint (IAM users) and return its HTTP status code."""
    return probe_endpoint(secret_key, organization_id, "users")
