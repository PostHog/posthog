import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlencode

from products.warehouse_sources.sources.rootly.settings import ROOTLY_ENDPOINTS, RootlyEndpointConfig
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

ROOTLY_BASE_URL = "https://api.rootly.com/v1"
# Rootly is a JSON:API service and expects/returns the JSON:API media type.
ROOTLY_JSON_API_MEDIA_TYPE = "application/vnd.api+json"


@dataclasses.dataclass(frozen=False)
class RootlyResumeConfig:
    # Full next-page URL from the JSON:API `links.next` field. It already carries the page,
    # sort, and filter params, so following it preserves the incremental window on every page.
    next_url: str | None = None
    # `meta.next_cursor` for cursor-paginated feeds; the original params are re-sent with it.
    cursor: str | None = None
    # Fan-out endpoints resume by parent: the parent paths already fully synced, the parent in
    # progress, and that parent's paginator state.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def _accept_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret JSON:API Accept header is set here.
    return {"Accept": ROOTLY_JSON_API_MEDIA_TYPE}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL. Rootly is Rails/JSON:API and parses percent-encoded bracket params
    (`filter[updated_at][gt]`, `page[size]`) correctly, so standard urlencode is safe."""
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp for Rootly's date filters."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now. A future-dated record could push the cursor
    past now; asking for records newer than now is a no-op, so clamping keeps the filter sane."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: RootlyEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build query params for the first request to a Rootly collection endpoint."""
    params: dict[str, Any] = {"page[size]": config.page_size}

    if config.supports_incremental and should_use_incremental_field:
        # Cursor on the user's chosen field; fall back to the endpoint's first advertised field.
        field_name = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
        if field_name:
            # Sort ascending on the same field we filter on so rows arrive in watermark order and
            # the pipeline can checkpoint safely (matches SourceResponse.sort_mode="asc").
            params["sort"] = field_name
            if db_incremental_field_last_value:
                value = _clamp_future_value_to_now(db_incremental_field_last_value)
                params[f"filter[{field_name}][gt]"] = _format_incremental_value(value)

    return params


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource object's `attributes` into the root and keep `id`/`type`."""
    flattened = {k: v for k, v in item.items() if k != "attributes"}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        flattened.update(attributes)
    return flattened


def probe_credentials(api_key: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of a Rootly collection. Returns the HTTP status code, or None on a connection
    failure. Probes the given endpoint's path when set, else a generic, cheap collection."""
    config = ROOTLY_ENDPOINTS.get(endpoint) if endpoint else None
    if config is not None and config.fanout is not None:
        # A child path needs a parent id; access to the parent collection is the same scope check.
        config = ROOTLY_ENDPOINTS[config.fanout.parent_name]
    path = config.path if config else "/users"
    url = _build_url(f"{ROOTLY_BASE_URL}{path}", {"page[size]": 1})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", **_accept_headers()},
    )
    return status


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": ROOTLY_BASE_URL,
        "headers": _accept_headers(),
        # Auth (Bearer) goes through the framework auth config so its value is redacted from logs.
        "auth": {"type": "bearer", "token": api_key},
        # Rootly is JSON:API — the next page URL lives in the response body under `links.next`.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
    }


def _make_source_response(config: RootlyEndpointConfig, resource: Resource) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def _top_level_source(
    config: RootlyEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> SourceResponse:
    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        # A 200 body without `data` is treated as an empty page (JSON:API always carries
        # `data`), matching the old `data.get("data", [])` — so no data_selector_required.
        "data_selector": "data",
    }
    if config.pagination == "cursor":
        endpoint_config["paginator"] = JSONResponseCursorPaginator(
            cursor_path="meta.next_cursor", cursor_param="page[after]"
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": endpoint_config,
                # Rootly is JSON:API — hoist each item's `attributes` into the row root.
                "data_map": _flatten_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}
        elif resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint lands AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(RootlyResumeConfig(next_url=state["next_url"]))
        elif state and state.get("cursor"):
            resumable_source_manager.save_state(RootlyResumeConfig(cursor=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering is applied server-side via the `filter[<field>][gt]` param built into
        # `params` above, so the framework's own incremental injection is not used here.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, resource)


def _fanout_source(
    config: RootlyEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                RootlyResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=ROOTLY_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            # Fan-out children have no server-side time filter, so they always sync as full refresh.
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": "data"},
            child_endpoint_extra={"data_selector": "data"},
            page_size_param="page[size]",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )
    # The parent id is injected before this map runs, so it survives the `attributes` hoist.
    return _make_source_response(config, resource.add_map(_flatten_item))


def rootly_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ROOTLY_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    return _top_level_source(
        config,
        api_key,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )
