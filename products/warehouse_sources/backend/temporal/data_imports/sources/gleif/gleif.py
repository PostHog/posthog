from typing import Any, Optional
from urllib.parse import urlencode

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.settings import (
    BASE_URL,
    ENDPOINT_PATHS,
    INCREMENTAL_FIELDS,
    LEI_RECORDS,
    PAGE_SIZE,
)

_HEADERS = {"Accept": "application/vnd.api+json"}


@frozen
class GleifResumeConfig:
    # GLEIF's `links.next` is a full, self-contained URL (JSON:API convention) covering both
    # the cursor pagination `lei-records` uses and the page-number pagination the small
    # reference tables use.
    next_url: str


def _flatten_json_api_item(item: dict[str, Any]) -> dict[str, Any]:
    """Hoist a JSON:API resource's `attributes` to the row root, keeping the top-level `id`."""
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return {"id": item.get("id")}
    return {"id": item.get("id"), **attributes}


def _flatten_lei_record(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a `lei-records` resource, additionally promoting the two registration dates
    GLEIF nests under `registration` to top-level columns so the table can be partitioned and
    incremental sync can filter/checkpoint on them.
    """
    row = _flatten_json_api_item(item)
    registration = row.get("registration")
    if isinstance(registration, dict):
        row["initial_registration_date"] = registration.get("initialRegistrationDate")
        row["last_update_date"] = registration.get("lastUpdateDate")
    return row


def _format_gte_filter(value: Any) -> str:
    """Format a watermark as GLEIF's `>=` date filter value.

    `registration.lastUpdateDate` is stored (and persisted as the incremental watermark) as an
    ISO-8601 UTC timestamp string, which GLEIF's date filter accepts directly (verified live).
    """
    return f">={value}"


def gleif_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GleifResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    incremental_mode = should_use_incremental_field and bool(INCREMENTAL_FIELDS.get(endpoint))
    use_filter = incremental_mode and db_incremental_field_last_value is not None

    params: dict[str, Any] = {"page[size]": PAGE_SIZE}
    if endpoint == LEI_RECORDS:
        # `page[number]` pagination on `lei-records` is rejected past ~10,000 results (verified
        # live: page 51 at page[size]=200 returns 400), so every sync of this ~3.4M row endpoint
        # must traverse it via the opaque `page[cursor]` instead.
        params["page[cursor]"] = "*"
        params["sort"] = "registration.lastUpdateDate"
        if use_filter:
            params["filter[registration.lastUpdateDate]"] = {
                "type": "incremental",
                "convert": _format_gte_filter,
            }

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": _HEADERS,
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
            # `links.next` is response-controlled; pin every paginated/resumed request to the
            # GLEIF API host so a tampered next link can't redirect it elsewhere.
            "allowed_hosts": [],
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if incremental_mode
            else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "table_format": "delta",
                "endpoint": {
                    "path": ENDPOINT_PATHS[endpoint],
                    "params": params,
                    "data_selector": "data",
                },
                "data_map": _flatten_lei_record if endpoint == LEI_RECORDS else _flatten_json_api_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Called AFTER a page is yielded, so a crash re-yields the last page (merge/
        # replace both tolerate the duplicate) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(GleifResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=db_incremental_field_last_value if use_filter else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=["id"],
        sort_mode="asc",
        partition_mode="datetime" if endpoint == LEI_RECORDS else None,
        partition_format="month" if endpoint == LEI_RECORDS else None,
        partition_keys=["initial_registration_date"] if endpoint == LEI_RECORDS else None,
        column_hints=resource.column_hints,
    )


def validate_credentials() -> bool:
    """GLEIF's API is fully open with no authentication; the only thing to validate is that
    the service is reachable."""
    query = urlencode({"page[size]": 1})
    response = make_tracked_session().get(f"{BASE_URL}/lei-records?{query}", headers=_HEADERS)
    return response.status_code == 200
