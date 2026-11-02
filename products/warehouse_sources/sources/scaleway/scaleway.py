import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import (
    BILLING_CONSUMPTION_LOOKBACK_MONTHS,
    K8S_CLUSTERS_ENDPOINT,
    PAGE_SIZE,
    SCALEWAY_ENDPOINTS,
    ScalewayEndpointConfig,
)

BASE_URL = "https://api.scaleway.com"
REQUEST_TIMEOUT = 60

# Sentinel scope for endpoints that aren't region/zone-scoped, so the fan-out loop always iterates a
# non-empty list of exactly one pass.
_UNSCOPED = "_"


@dataclasses.dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new field shifts the backlog finding into diff
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
    # The scope at `scope_index`. Billing periods and clusters are built at run time, so their positions
    # can shift between attempts; resume finds the scope by this key instead.
    scope_key: str | None = None


def _get_headers(secret_key: str) -> dict[str, str]:
    # Scaleway authenticates every request with the API secret key in the X-Auth-Token header.
    return {"X-Auth-Token": secret_key, "Accept": "application/json"}


def _format_rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _billing_periods(now: datetime) -> list[str]:
    """The `YYYY-MM` billing periods of the consumption window, oldest first, ending with the current month."""
    periods = []
    year, month = now.year, now.month
    for _ in range(BILLING_CONSUMPTION_LOOKBACK_MONTHS):
        periods.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(periods))


def _scopes_for(config: ScalewayEndpointConfig) -> list[str]:
    if config.scope in ("region", "zone"):
        return config.scope_values
    if config.scope == "billing_period":
        return _billing_periods(datetime.now(UTC))
    if config.scope == "k8s_cluster":
        raise ValueError("Cluster scopes come from the API, see _list_cluster_scopes")
    return [_UNSCOPED]


def _resolve_path(config: ScalewayEndpointConfig, scope: str) -> str:
    if config.scope == "region":
        return config.path.format(region=scope)
    if config.scope == "zone":
        return config.path.format(zone=scope)
    if config.scope == "k8s_cluster":
        region, cluster_id = scope.split("/", 1)
        return config.path.format(region=region, cluster_id=cluster_id)
    return config.path


def _scope_params(config: ScalewayEndpointConfig, scope: str) -> dict[str, Any]:
    if config.scope == "billing_period":
        return {"billing_period": scope}
    return {}


def _shape_rows(config: ScalewayEndpointConfig, scope: str, items: list[dict]) -> list[dict]:
    # Consumption rows do not say which month they belong to, so carry the requested period on each row.
    if config.scope == "billing_period":
        return [{**item, "billing_period": scope} for item in items]
    return items


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


def _list_cluster_scopes(
    session: requests.Session,
    config: ScalewayEndpointConfig,
    organization_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ScalewayResumeConfig],
) -> list[str]:
    """List every Kubernetes cluster in the endpoint's regions as `<region>/<cluster_id>` scope keys."""
    clusters_config = SCALEWAY_ENDPOINTS[K8S_CLUSTERS_ENDPOINT]
    params = _base_params(clusters_config, organization_id)
    scopes: list[str] = []
    for region in config.scope_values:
        url = f"{BASE_URL}{_resolve_path(clusters_config, region)}"
        for clusters, _has_more, _next_cursor in _iter_pages(session, url, params, clusters_config, logger, None, None):
            scopes.extend(f"{region}/{cluster['id']}" for cluster in clusters)
            # Listing yields no rows, and no cursor is staged yet, so a hand-off here only restarts the listing.
            resumable_source_manager.safe_point()
    return scopes


def _resume_index(scopes: list[str], resume: ScalewayResumeConfig) -> int | None:
    """The index of the scope to resume into, or None when the saved scope no longer exists."""
    if resume.scope_key is None:
        return resume.scope_index
    try:
        return scopes.index(resume.scope_key)
    except ValueError:
        return None


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
    if config.scope == "k8s_cluster":
        scopes = _list_cluster_scopes(session, config, organization_id, logger, resumable_source_manager)
    else:
        scopes = _scopes_for(config)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    if resume is not None:
        resume_index = _resume_index(scopes, resume)
        if resume_index is None:
            # The saved cluster was deleted, or the saved billing period left the window: start over.
            resume = None
        else:
            start_index = resume_index
    if start_index >= len(scopes):
        return

    for scope_index in range(start_index, len(scopes)):
        scope = scopes[scope_index]
        url = f"{BASE_URL}{_resolve_path(config, scope)}"
        scope_params = {**base_params, **_scope_params(config, scope)}
        # Only the scope we resumed into consumes the saved page/token cursor; later scopes start fresh.
        if resume is not None and scope_index == start_index:
            start_page = resume.page
            start_token = resume.page_token
        else:
            start_page = None
            start_token = None

        try:
            for items, has_more, next_cursor in _iter_pages(
                session, url, scope_params, config, logger, start_page, start_token
            ):
                if items:
                    yield _shape_rows(config, scope, items)
                else:
                    # Empty regions, clusters and months return no rows, so the pipeline sees no item here.
                    resumable_source_manager.safe_point()
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it (merge
                # dedupes on the primary key). Only persist when more pages remain in this scope.
                if has_more:
                    resumable_source_manager.save_state(
                        ScalewayResumeConfig(scope_index=scope_index, scope_key=scope, **next_cursor)
                    )
        except requests.HTTPError as e:
            # A cluster deleted after it was listed answers 404; skip it instead of failing the whole table.
            if config.scope == "k8s_cluster" and e.response is not None and e.response.status_code == 404:
                logger.warning(f"Scaleway cluster {scope} no longer exists, skipping it")
            else:
                raise

        # Advance the bookmark to the next scope so a crash between scopes resumes correctly.
        if scope_index + 1 < len(scopes):
            resumable_source_manager.save_state(
                ScalewayResumeConfig(scope_index=scope_index + 1, scope_key=scopes[scope_index + 1])
            )


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
    if config.scope == "k8s_cluster":
        # Pools and nodes need a cluster in the path. Listing clusters needs the same Kubernetes read permission.
        config = SCALEWAY_ENDPOINTS[K8S_CLUSTERS_ENDPOINT]
    session = make_tracked_session(headers=_get_headers(secret_key), redact_values=(secret_key,))
    scope = _scopes_for(config)[0]
    url = f"{BASE_URL}{_resolve_path(config, scope)}"
    params = {**_base_params(config, organization_id), **_scope_params(config, scope)}
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
