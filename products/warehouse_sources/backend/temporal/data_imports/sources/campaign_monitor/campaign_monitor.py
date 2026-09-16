import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

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
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CAMPAIGN_MONITOR_BASE_URL = "https://api.createsend.com/api/v3.3"
DEFAULT_PAGE_SIZE = 1000  # Campaign Monitor's documented maximum page size.
# Subscriber-state endpoints require a `date`; this fetches the full history (the filter is
# inclusive from the given date onward). Used until server-side incremental is verified live.
FULL_REFRESH_SINCE_DATE = "1900-01-01"
# The journey report endpoints document their `date` as `YYYY-MM-DD HH:MM`, and default it to the
# last 30 days when it is omitted — so it always has to be sent.
JOURNEY_FULL_REFRESH_SINCE_DATE = "1900-01-01 00:00"
# Intermediate resource fanning the journey summary out into one row per journey email. Not a
# synced table: it exists so the journey report endpoints have an `EmailID` to resolve.
JOURNEY_EMAILS_RESOURCE = "journey_emails"


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
    if config.journey_report:
        params["date"] = JOURNEY_FULL_REFRESH_SINCE_DATE
        params["orderdirection"] = "asc"
        return params
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


def _inject_parent_ids(renames: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any] | list[Any]]:
    def _map(row: dict[str, Any]) -> dict[str, Any] | list[Any]:
        values = {target: row.pop(prefixed, None) for prefixed, target in renames.items()}
        if not row:
            # An empty body (e.g. a summary object with no fields) is not a row — drop it rather
            # than emitting a record that carries only the injected parent ids.
            return []
        for target, value in values.items():
            if value is not None:
                row[target] = value
        return row

    return _map


def _journeys_resource(client_id: str) -> EndpointResource:
    # The client journeys endpoint returns a bare JSON array.
    return {
        "name": "journeys",
        "endpoint": {
            "path": f"clients/{client_id}/journeys.json",
            "paginator": SinglePagePaginator(),
            "data_selector_required": True,
        },
    }


def _journey_emails_resource(name: str) -> EndpointResource:
    """One row per journey email, read out of the journey summary's nested `Emails` array. Serves
    both as the `journey_email_summary` table and as the parent the journey report endpoints
    resolve their `EmailID` from — the journeys list itself carries no email ids."""
    return {
        "name": name,
        "endpoint": {
            "path": "journeys/{journey_id}.json",
            "params": {"journey_id": {"type": "resolve", "resource": "journeys", "field": "JourneyID"}},
            "paginator": SinglePagePaginator(),
            # A journey with no emails yields a zero-row page rather than failing the sync.
            "data_selector": "Emails",
        },
        "include_from_parent": ["JourneyID"],
        "data_map": _inject_parent_ids({"_journeys_JourneyID": "JourneyID"}),
    }


def _child_resource(
    config: CampaignMonitorEndpointConfig,
    parent_name: str,
    resolve_param: str,
    resolve_field: str,
    parent_columns: list[str],
) -> EndpointResource:
    params: dict[str, Any] = {
        resolve_param: {"type": "resolve", "resource": parent_name, "field": resolve_field},
    }

    endpoint: Endpoint
    if config.paginated:
        params.update(_page_params(config))
        endpoint = {
            "path": config.path,
            "params": params,
            "paginator": _paginator(),
            "data_selector": "Results",
        }
    else:
        # Single-object endpoints (e.g. campaign summary) return one JSON object per parent,
        # which the framework wraps as a single row.
        endpoint = {
            "path": config.path,
            "params": params,
            "paginator": SinglePagePaginator(),
        }

    return {
        "name": config.name,
        "endpoint": endpoint,
        "include_from_parent": parent_columns,
        # include_from_parent lands each parent column as `_<parent>_<column>`; rename them to the
        # plain columns the composite primary keys expect.
        "data_map": _inject_parent_ids({f"_{parent_name}_{column}": column for column in parent_columns}),
    }


def _fan_out_resource(
    api_key: str,
    client_id: str,
    config: CampaignMonitorEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> Resource:
    """Fan a scoped endpoint out over every parent via dependent resources: the framework walks the
    parents, pages each parent's child endpoint, and injects the parent ids into every row. The
    journey report endpoints hang off a two-level chain, because a journey email id is exposed
    nowhere but inside the journey summary."""
    resources: list[str | EndpointResource]
    if config.fan_out_over_journeys:
        # The journey-emails resource IS this endpoint: the summary's `Emails` array is the table.
        resources = [_journeys_resource(client_id), _journey_emails_resource(config.name)]
    elif config.journey_report:
        resources = [
            _journeys_resource(client_id),
            _journey_emails_resource(JOURNEY_EMAILS_RESOURCE),
            _child_resource(config, JOURNEY_EMAILS_RESOURCE, "email_id", "EmailID", ["EmailID", "JourneyID"]),
        ]
    elif config.fan_out_over_lists:
        resources = [
            {
                "name": "lists",
                "endpoint": {
                    # The subscriber-lists endpoint returns a bare JSON array.
                    "path": f"clients/{client_id}/lists.json",
                    "paginator": SinglePagePaginator(),
                    "data_selector_required": True,
                },
            },
            _child_resource(config, "lists", "list_id", "ListID", ["ListID"]),
        ]
    else:
        resources = [
            {
                "name": "campaigns",
                "endpoint": {
                    # Only sent campaigns have reports, which is exactly what campaigns.json
                    # returns — in the standard paged envelope (`{"Results": [...],
                    # "NumberOfPages": N, ...}`), not a bare array like the draft/scheduled
                    # campaign endpoints.
                    "path": f"clients/{client_id}/campaigns.json",
                    "params": {"pagesize": DEFAULT_PAGE_SIZE},
                    "paginator": _paginator(),
                    "data_selector": "Results",
                },
            },
            _child_resource(config, "campaigns", "campaign_id", "CampaignID", ["CampaignID"]),
        ]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": resources,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only framework-shaped fan-out state is resumable. A pre-migration bookmark
        # (list_id/campaign_id + page) can't be translated into the completed/current path map, so
        # such a sync restarts fresh — safe, because the merge dedupes re-pulled rows on the
        # primary key. Nothing is ever saved for the two-level journey chain: the framework
        # declines to share one resume hook across several dependent levels.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(CampaignMonitorResumeConfig(fanout_state=state))

    built = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in built if r.name == config.name)


def campaign_monitor_source(
    api_key: str,
    client_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> SourceResponse:
    config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]

    if config.is_fanned_out:
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
