import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.sources.planning_center.settings import (
    PAGE_SIZE,
    PLANNING_CENTER_BASE_URL,
    PLANNING_CENTER_ENDPOINTS,
    PRODUCT_API_VERSIONS,
    PlanningCenterEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    IncrementalConfig,
    OffsetPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

UPDATED_AT_FILTER_PARAM = "where[updated_at][gte]"

# The first incremental sync has no watermark. Every row has an `updated_at` after this value, so the
# filter returns the full history.
INITIAL_UPDATED_AT = "1970-01-01T00:00:00Z"

# JSON:API envelope keys that `flatten_resource` replaces with flat columns.
_JSON_API_KEYS = frozenset({"type", "attributes", "relationships", "links", "meta"})


@dataclasses.dataclass(frozen=True)
class PlanningCenterResumeConfig:
    next_offset: Optional[int] = None
    # Resume state of the plans fan-out, opaque to this source and passed back to the fan-out helper.
    fanout_state: Optional[dict[str, Any]] = None


def format_updated_at(value: Any) -> str:
    """Format a cursor value for `where[updated_at][gte]`.

    The API reads a date with no time in the organization's time zone, so the filter always gets a full
    UTC timestamp. Seconds are truncated, which re-reads at most one second of rows. Merge on the
    primary key removes those duplicates.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def flatten_resource(item: dict[str, Any]) -> dict[str, Any]:
    """Turn a JSON:API resource object into one flat row.

    `attributes` move to the row root. A to-one relationship becomes `<name>_id` and a to-many
    relationship becomes `<name>_ids`. A value that is already on the row wins over a relationship
    id, because some resources also send the id as an attribute (`person_id` on notes) and a fan-out
    child already carries its parent id.
    """
    row = {key: value for key, value in item.items() if key not in _JSON_API_KEYS}

    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        for key, value in attributes.items():
            if key not in row:
                row[key] = value

    relationships = item.get("relationships")
    if isinstance(relationships, dict):
        for name, relationship in relationships.items():
            # A relationship without `data` only has links, so it carries no id.
            if not isinstance(relationship, dict) or "data" not in relationship:
                continue
            data = relationship["data"]
            if isinstance(data, list):
                row.setdefault(f"{name}_ids", [entry.get("id") for entry in data if isinstance(entry, dict)])
            else:
                row.setdefault(f"{name}_id", data.get("id") if isinstance(data, dict) else None)

    return row


def _incremental_config(_cursor_path: str) -> IncrementalConfig:
    return {
        "start_param": UPDATED_AT_FILTER_PARAM,
        "cursor_path": "updated_at",
        "initial_value": INITIAL_UPDATED_AT,
        "convert": format_updated_at,
    }


def _order_param(config: PlanningCenterEndpointConfig, use_incremental: bool) -> dict[str, str]:
    if use_incremental:
        return {"order": "updated_at"} if config.orders_by_updated_at else {}
    return {"order": config.full_refresh_order} if config.full_refresh_order else {}


def _paginator() -> OffsetPaginator:
    return OffsetPaginator(
        limit=PAGE_SIZE,
        offset_param="offset",
        limit_param="per_page",
        total_path="meta.total_count",
    )


def _client_config(application_id: str, secret: str, product: str) -> ClientConfig:
    return {
        "base_url": PLANNING_CENTER_BASE_URL,
        "headers": {"X-PCO-API-Version": PRODUCT_API_VERSIONS[product]},
        "auth": {"type": "http_basic", "username": application_id, "password": secret},
        "paginator": _paginator(),
    }


def _source_response(config: PlanningCenterEndpointConfig, resource: Any, use_incremental: bool) -> SourceResponse:
    # Rows arrive in ascending `updated_at` order only on an incremental read of a top-level endpoint
    # that sorts on `updated_at`. A fan-out restarts the order for each parent.
    ordered = use_incremental and config.orders_by_updated_at and config.fanout is None
    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc" if ordered else None,
    )


def _top_level_source(
    application_id: str,
    secret: str,
    config: PlanningCenterEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PlanningCenterResumeConfig],
    use_incremental: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    endpoint: Endpoint = {
        "path": config.path,
        "params": _order_param(config, use_incremental),
        "data_selector": "data",
    }
    if use_incremental:
        endpoint["incremental"] = _incremental_config("updated_at")

    rest_config: RESTAPIConfig = {
        "client": _client_config(application_id, secret, config.product),
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "primary_key": config.primary_keys,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
                "endpoint": endpoint,
                "data_map": flatten_resource,
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_offset is not None:
            initial_paginator_state = {"offset": resume.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(PlanningCenterResumeConfig(next_offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(config, resource, use_incremental)


def _fanout_source(
    application_id: str,
    secret: str,
    config: PlanningCenterEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PlanningCenterResumeConfig],
    use_incremental: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    assert config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(PlanningCenterResumeConfig(fanout_state=state))

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=PLANNING_CENTER_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(application_id, secret, config.product),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value if use_incremental else None,
            should_use_incremental_field=use_incremental,
            incremental_field="updated_at" if use_incremental else None,
            incremental_config_factory=_incremental_config,
            parent_endpoint_extra={"data_selector": "data", "paginator": _paginator()},
            child_endpoint_extra={"data_selector": "data", "paginator": _paginator()},
            child_params_extra=_order_param(config, use_incremental),
            # The paginator sends `per_page` on every request.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )
    # Added after the helper renames the parent id, so `service_type_id` is already on the row.
    resource.add_map(flatten_resource)
    return _source_response(config, resource, use_incremental)


def planning_center_source(
    application_id: str,
    secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PlanningCenterResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PLANNING_CENTER_ENDPOINTS[endpoint]
    use_incremental = should_use_incremental_field and config.incremental
    build = _fanout_source if config.fanout is not None else _top_level_source
    return build(
        application_id,
        secret,
        config,
        team_id,
        job_id,
        resumable_source_manager,
        use_incremental,
        db_incremental_field_last_value,
    )


def probe_status(application_id: str, secret: str, path: str, product: str) -> Optional[int]:
    """GET one row of `path`. Returns the HTTP status, or None when the request itself failed."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(secret,)),
        f"{PLANNING_CENTER_BASE_URL}{path}?per_page=1",
        headers={"X-PCO-API-Version": PRODUCT_API_VERSIONS[product]},
        auth=HTTPBasicAuth(application_id, secret),
    )
    return status


def probe_endpoint_status(application_id: str, secret: str, endpoint: str) -> Optional[int]:
    config = PLANNING_CENTER_ENDPOINTS[endpoint]
    # A fan-out child path holds an unbound parent id, so probe the parent list, which needs the same access.
    if config.fanout is not None:
        config = PLANNING_CENTER_ENDPOINTS[config.fanout.parent_name]
    return probe_status(application_id, secret, config.path, config.product)
