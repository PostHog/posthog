import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import (
    CAMPAIGN_MONITOR_ENDPOINTS,
    CampaignMonitorEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CAMPAIGN_MONITOR_BASE_URL = "https://api.createsend.com/api/v3.3"
DEFAULT_PAGE_SIZE = 1000  # Campaign Monitor's documented maximum page size.
# Subscriber-state endpoints require a `date`; this fetches the full history (the filter is
# inclusive from the given date onward). Used until server-side incremental is verified live.
FULL_REFRESH_SINCE_DATE = "1900-01-01"


@dataclasses.dataclass
class CampaignMonitorResumeConfig:
    # Pre-framework fan-out bookmarks. Kept (with defaults) so previously saved state still
    # parses; no longer written — fan-out resume now lives in fanout_state.
    list_id: str | None = None
    campaign_id: str | None = None
    # Next page to fetch (1-based) on a top-level paginated endpoint. Always 1 otherwise.
    page: int = 1
    # Framework fan-out resume state for list-/campaign-scoped endpoints:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


def _client_config(api_key: str) -> ClientConfig:
    # Campaign Monitor uses the API key as the HTTP Basic username; the password is ignored.
    # Framework auth (not a hand-built header) so the key is redacted from logged URLs/headers.
    return {
        "base_url": CAMPAIGN_MONITOR_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "http_basic", "username": api_key, "password": "x"},
    }


def _paginator() -> PageNumberPaginator:
    # Paged envelopes are `{"Results": [...], "NumberOfPages": N, ...}` with 1-based pages;
    # NumberOfPages is the TOTAL NUMBER OF PAGES, so pagination stops after the last page.
    return PageNumberPaginator(base_page=1, page_param="page", total_path="NumberOfPages")


def _page_params(config: CampaignMonitorEndpointConfig) -> dict[str, Any]:
    # The `page` param itself is injected by the paginator.
    params: dict[str, Any] = {"pagesize": DEFAULT_PAGE_SIZE}
    if config.uses_date_filter:
        params["date"] = FULL_REFRESH_SINCE_DATE
    if config.order_field:
        # `orderfield` keeps pagination stable across the sync.
        params["orderfield"] = config.order_field
        params["orderdirection"] = "asc"
    return params


def _top_level_resource(
    api_key: str,
    client_id: str,
    config: CampaignMonitorEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> Resource:
    path = config.path.format(client_id=client_id)

    endpoint: Endpoint
    if config.paginated:
        # A body without `Results` yields a zero-row page and pagination stops — same tolerant
        # behavior the API's empty envelopes get.
        endpoint = {
            "path": path,
            "params": _page_params(config),
            "paginator": _paginator(),
            "data_selector": "Results",
        }
    else:
        # Bare-array endpoints: a non-list 200 body means the response shape changed — fail loud
        # instead of syncing a stray object as a row.
        endpoint = {
            "path": path,
            "paginator": SinglePagePaginator(),
            "data_selector_required": True,
        }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [{"name": config.name, "endpoint": endpoint}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.page > 1:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER a page is yielded so
        # a crash re-fetches the in-flight page (the merge dedupes re-pulled rows) rather than
        # skipping it.
        if state and state.get("page") is not None:
            manager.save_state(CampaignMonitorResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _inject_parent_id(prefixed_key: str, target_key: str) -> Callable[[dict[str, Any]], dict[str, Any] | list[Any]]:
    def _map(row: dict[str, Any]) -> dict[str, Any] | list[Any]:
        value = row.pop(prefixed_key, None)
        if not row:
            # An empty body (e.g. a summary object with no fields) is not a row — drop it rather
            # than emitting a record that carries only the injected parent id.
            return []
        if value is not None:
            row[target_key] = value
        return row

    return _map


def _fan_out_resource(
    api_key: str,
    client_id: str,
    config: CampaignMonitorEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> Resource:
    """Fan a list-/campaign-scoped endpoint out over every parent via a dependent resource: the
    framework fetches the client's lists (or sent campaigns), pages each parent's child endpoint,
    and injects the parent id into every row."""
    if config.fan_out_over_lists:
        parent_name = "lists"
        parent_path = f"clients/{client_id}/lists.json"
        resolve_param, parent_id_field = "list_id", "ListID"
    else:
        # Only sent campaigns have reports, which is exactly what campaigns.json returns.
        parent_name = "campaigns"
        parent_path = f"clients/{client_id}/campaigns.json"
        resolve_param, parent_id_field = "campaign_id", "CampaignID"

    child_params: dict[str, Any] = {
        resolve_param: {"type": "resolve", "resource": parent_name, "field": parent_id_field},
    }
    child_endpoint: Endpoint
    if config.paginated:
        child_params.update(_page_params(config))
        child_endpoint = {
            "path": config.path,
            "params": child_params,
            "paginator": _paginator(),
            "data_selector": "Results",
        }
    else:
        # Single-object endpoints (e.g. campaign summary) return one JSON object per parent,
        # which the framework wraps as a single row.
        child_endpoint = {
            "path": config.path,
            "params": child_params,
            "paginator": SinglePagePaginator(),
        }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": parent_name,
                "endpoint": {
                    "path": parent_path,
                    "paginator": SinglePagePaginator(),
                    "data_selector_required": True,
                },
            },
            {
                "name": config.name,
                "endpoint": child_endpoint,
                "include_from_parent": [parent_id_field],
                # include_from_parent lands the parent id as `_lists_ListID`/`_campaigns_CampaignID`;
                # rename it to the plain column the composite primary keys expect.
                "data_map": _inject_parent_id(f"_{parent_name}_{parent_id_field}", parent_id_field),
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only framework-shaped fan-out state is resumable. A pre-migration bookmark
        # (list_id/campaign_id + page) can't be translated into the completed/current path map, so
        # such a sync restarts fresh — safe, because the merge dedupes re-pulled rows on the
        # primary key.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(CampaignMonitorResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == config.name)


def campaign_monitor_source(
    api_key: str,
    client_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> SourceResponse:
    config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]

    if config.fan_out_over_lists or config.fan_out_over_campaigns:
        resource = _fan_out_resource(api_key, client_id, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(api_key, client_id, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Cheap probe that confirms the API key is genuine via the account-level clients endpoint."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CAMPAIGN_MONITOR_BASE_URL}/clients.json",
        auth=HTTPBasicAuth(api_key, "x"),
    )
    return ok
