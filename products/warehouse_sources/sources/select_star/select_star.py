from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    JSONResponsePaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.select_star.settings import (
    PAGE_SIZE,
    SELECTSTAR_BASE_URL,
    SELECTSTAR_ENDPOINTS,
    SelectStarEndpointConfig,
)


@frozen
class SelectStarResumeConfig:
    next_url: Optional[str] = None
    # Framework fan-out state for the per-parent endpoints, passed straight back to
    # `build_dependent_resource`.
    fanout_state: Optional[dict[str, Any]] = None


def _auth_header_value(api_token: str) -> str:
    # Select Star requires the "Token" scheme, not "Bearer".
    return f"Token {api_token}"


def _incremental_param(field: str) -> dict[str, Any]:
    return {"type": "incremental", "cursor_path": field, "initial_value": None}


def _client_config(api_token: str) -> ClientConfig:
    return {
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
    }


def _flatten_tagged_item(row: dict[str, Any]) -> dict[str, Any]:
    item = row.get("item") or {}
    obj = item.get("obj") or {}
    row["item_guid"] = obj.get("guid")
    row["item_object_type"] = item.get("object_type")
    return row


def _fanout_source(
    api_token: str,
    endpoint: str,
    config: SelectStarEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SelectStarResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = SELECTSTAR_ENDPOINTS[config.fanout.parent_name]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(SelectStarResumeConfig(fanout_state=state))

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=SELECTSTAR_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # The parent page size rides in `parent_params`; the child endpoints document no page size.
            page_size_param=None,
            parent_endpoint_extra={"data_selector": parent_config.data_selector},
            child_endpoint_extra={
                "data_selector": config.data_selector,
                **({} if config.paginated else {"paginator": SinglePagePaginator()}),
            },
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
            # Saves the parent page too, so the checkpoint keeps two pages of finished parents
            # rather than every table in a large catalog.
            resume_parent_pagination=True,
        ),
    )
    if endpoint == "TaggedItems":
        resource.add_map(_flatten_tagged_item)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
    )


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
    if config.fanout is not None:
        return _fanout_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager)

    # inputs.incremental_field is the user's chosen cursor (menu = config.incremental_fields);
    # fall back to the first advertised option so a schema saved before the user picks stays usable.
    filter_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
    use_incremental = should_use_incremental_field and filter_field is not None

    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if filter_field:
        params[f"{filter_field}__gte"] = _incremental_param(filter_field) if use_incremental else None

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
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
        if resume is not None and resume.next_url:
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
