from typing import Any, Optional

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.settings import (
    PAGE_SIZE,
    SELECTSTAR_BASE_URL,
    SELECTSTAR_ENDPOINTS,
)


@frozen
class SelectStarResumeConfig:
    next_url: str


def _auth_header_value(api_token: str) -> str:
    # Select Star requires the "Token" scheme, not "Bearer".
    return f"Token {api_token}"


def _incremental_param(field: str) -> dict[str, Any]:
    return {"type": "incremental", "cursor_path": field, "initial_value": None}


def select_star_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SelectStarResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = SELECTSTAR_ENDPOINTS[endpoint]

    # inputs.incremental_field is the user's chosen cursor (menu = config.incremental_fields);
    # fall back to the first advertised option so a schema saved before the user picks stays usable.
    filter_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
    use_incremental = should_use_incremental_field and filter_field is not None

    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if filter_field:
        params[f"{filter_field}__gte"] = _incremental_param(filter_field) if use_incremental else None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SELECTSTAR_BASE_URL,
            "auth": {
                "type": "api_key",
                "api_key": _auth_header_value(api_token),
                "name": "Authorization",
                "location": "header",
            },
            "paginator": JSONResponsePaginator(next_url_path="next"),
            # Pagination follows the absolute `next` URL straight out of the response body, and
            # the API token is replayed on every request via the Authorization header, so pin
            # follow-up requests to the API host and refuse redirects: a tampered `next` link must
            # not be able to retarget the token off-host (SSRF).
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {
            "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash
        # re-fetches the last in-flight page (merge dedupes on the primary key) rather than
        # skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SelectStarResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> tuple[bool, Optional[str]]:
    """Cheap probe against the tables list endpoint to confirm the token is genuine."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{SELECTSTAR_BASE_URL}/v1/tables/?page_size=1",
        headers={"Authorization": _auth_header_value(api_token)},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Select Star rejected the API token. Generate a new token in Account Settings and reconnect."
    if status == 403:
        return (
            False,
            "This Select Star token doesn't have permission to read the catalog. Check the user's "
            "role in Account Settings and reconnect.",
        )
    return False, "Could not verify the Select Star API token. Check your network and try again."
