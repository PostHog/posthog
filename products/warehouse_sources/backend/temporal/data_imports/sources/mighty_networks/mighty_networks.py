import dataclasses
from collections.abc import Callable
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.settings import (
    BASE_URL,
    ENDPOINT_CONFIGS,
    FANOUTS,
    PARTITION_FIELDS,
    PATHS,
    PER_PAGE,
    PRIMARY_KEYS,
)

# Mighty Networks blocks requests without a descriptive User-Agent as bot traffic, returning an
# HTML challenge page with HTTP 403 instead of a JSON error.
USER_AGENT = "PostHog-DataWarehouse/1.0 (+https://posthog.com)"


@dataclasses.dataclass(frozen=False)
class MightyNetworksResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: Optional[int] = None
    # `build_dependent_resource` checkpoint for the per-parent walk of a fan-out endpoint.
    fanout_state: Optional[dict[str, Any]] = None


def _network_url(network_id: str, path: str = "") -> str:
    return f"{BASE_URL}/networks/{network_id}{path}"


def _flatten_subscription(row: dict[str, Any]) -> dict[str, Any]:
    # The subscription's own id lives under a nested `subscription` object; lift it to the row
    # root so `primary_keys=["id"]` has a flat column to merge on.
    subscription = row.get("subscription")
    if isinstance(subscription, dict) and "id" in subscription:
        row["id"] = subscription["id"]
    return row


def _flatten_purchase(row: dict[str, Any]) -> dict[str, Any]:
    # Same shape as subscriptions: the purchase's id, created_at and updated_at all live under a
    # nested `purchase` object rather than the row root.
    purchase = row.get("purchase")
    if isinstance(purchase, dict):
        for field in ("id", "created_at", "updated_at"):
            if field in purchase:
                row[field] = purchase[field]
    return row


_ROW_FIXUPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "Subscriptions": _flatten_subscription,
    "Purchases": _flatten_purchase,
}


# The docs show two different placeholder envelopes for list responses ("data"/meta and
# "items"/links); "data" is the one paired with the concrete meta fields
# (current_page/total_pages/total_count) the paginator relies on, so it's the more likely real
# field name. Fail loud if that's wrong rather than silently syncing zero rows.
_DATA_SELECTOR: Endpoint = {"data_selector": "data", "data_selector_required": True}


_UNBOUNDED_FANOUT_PARENTS = frozenset({"Members", "Events"})


def _client_config(api_key: str, network_id: str) -> ClientConfig:
    return {
        "base_url": _network_url(network_id),
        "headers": {"User-Agent": USER_AGENT, "Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="meta.total_pages"),
    }


def _fanout_resource(
    api_key: str,
    network_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MightyNetworksResumeConfig],
) -> Resource:
    fanout = FANOUTS[endpoint]
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    resume: Optional[MightyNetworksResumeConfig] = None
    # The fan-out checkpoint lists every completed parent, so it grows without bound when the
    # parent is a network-wide list like Members or Events. Those children are short, so a restart
    # costs little. Spaces and Plans are few, and their member lists are long.
    if fanout.parent_name not in _UNBOUNDED_FANOUT_PARENTS:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        def resume_hook(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(MightyNetworksResumeConfig(fanout_state=state))

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=ENDPOINT_CONFIGS,
            child_endpoint=endpoint,
            fanout=fanout,
            client_config=_client_config(api_key, network_id),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=_DATA_SELECTOR,
            child_endpoint_extra=_DATA_SELECTOR,
            page_size_param="per_page",
            resume_hook=resume_hook,
            initial_paginator_state=resume.fanout_state if resume else None,
        ),
    )


def _list_resource(
    api_key: str,
    network_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MightyNetworksResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, network_id),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [
            {
                "name": endpoint,
                "write_disposition": "replace",
                "endpoint": {
                    "path": PATHS[endpoint],
                    "params": {"per_page": PER_PAGE},
                    **_DATA_SELECTOR,
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(MightyNetworksResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    fixup = _ROW_FIXUPS.get(endpoint)
    if fixup is not None:
        resource = resource.add_map(fixup)
    return resource


def mighty_networks_source(
    api_key: str,
    network_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MightyNetworksResumeConfig],
) -> SourceResponse:
    build = _fanout_resource if endpoint in FANOUTS else _list_resource
    resource = build(api_key, network_id, endpoint, team_id, job_id, resumable_source_manager)

    partition_key = PARTITION_FIELDS.get(endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS.get(endpoint, ["id"]),
        column_hints=resource.column_hints,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def validate_credentials(api_key: str, network_id: str) -> tuple[bool, int | None]:
    """Probe Mighty Networks' `/me` endpoint to confirm the token (and network id) are genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        _network_url(network_id, "/me"),
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def _probe_path(endpoint: str) -> str:
    # A fan-out child has no list path without a parent id, so probe the parent list it walks.
    fanout = FANOUTS.get(endpoint)
    return PATHS[fanout.parent_name] if fanout else PATHS[endpoint]


def check_endpoint_access(api_key: str, network_id: str, endpoint: str) -> Optional[str]:
    """Probe a single list endpoint and report why it's inaccessible, or ``None`` if it's fine.

    Only a genuine 403 (valid token, missing permission) counts as a permission problem — a
    throttle, 5xx, or network blip should not deselect a table the user can actually sync.
    """
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            _network_url(network_id, _probe_path(endpoint)),
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT, "Accept": "application/json"},
            params={"per_page": 1},
            timeout=10,
        )
    except Exception:
        return None

    if response.status_code != 403:
        return None

    try:
        message = response.json().get("message")
    except Exception:
        message = None

    return message or "Your Mighty Networks API token doesn't have permission to read this data."
