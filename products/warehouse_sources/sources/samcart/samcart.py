import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.sources.samcart.settings import (
    API_VERSION,
    BASE_URL,
    PAGE_SIZE,
    PARTITION_KEY,
    SAMCART_ENDPOINTS,
    SORT,
    SamCartEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    JSONResponseCursorPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

# Cheap list endpoint used to confirm the API key. A key reads the whole marketplace, so one probe
# covers every table.
PROBE_PATH = f"/{API_VERSION}/charges"

UTM_COLUMNS = {
    "utm_source": "source",
    "utm_medium": "medium",
    "utm_campaign": "campaign",
    "utm_content": "content",
    "lead_source": "lead_source",
}


@dataclasses.dataclass(frozen=False)
class SamCartResumeConfig:
    cursor: Optional[str] = None
    fanout_state: Optional[dict[str, Any]] = None


def _format_created_at_min(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _list_params(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "sort": SORT}
    # The filter is sent only once a watermark exists: `created_at` is nullable, and a filter on the
    # first sync would drop the records that have no value.
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["created_at_min"] = _format_created_at_min(db_incremental_field_last_value)
    return params


def _cursor_paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path="meta.next_cursor", cursor_param="cursor")


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "sc-api", "api_key": api_key, "location": "header"},
        # requests keeps the custom `sc-api` header on a cross-origin redirect, so a redirect could hand
        # the key to another host. Cursor pagination never needs one.
        "allow_redirects": False,
    }


def add_utm_columns(order: dict[str, Any]) -> dict[str, Any]:
    # `attribution_enhanced` merges the new capture system with the legacy one, so it wins. The
    # legacy `attribution` block fills a value that the enhanced block does not have.
    enhanced = (order.get("attribution_enhanced") or {}).get("utm_parameters") or {}
    legacy = (order.get("attribution") or {}).get("utm_parameters") or {}
    for column, key in UTM_COLUMNS.items():
        order[column] = enhanced.get(key) or legacy.get(key)
    return order


def _source_response(endpoint: str, config: SamCartEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[PARTITION_KEY],
    )


def _orders_source(
    api_key: str,
    endpoint: str,
    config: SamCartEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SamCartResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    assert config.fanout is not None
    fanout = dataclasses.replace(
        config.fanout,
        parent_params=_list_params(should_use_incremental_field, db_incremental_field_last_value),
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(SamCartResumeConfig(fanout_state=state))

    resource = build_dependent_resource(
        endpoint_configs=SAMCART_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        should_use_incremental_field=should_use_incremental_field,
        # The order detail endpoint has no time filter. The watermark bounds the order list instead.
        incremental_config_factory=lambda _field: None,
        parent_endpoint_extra={"paginator": _cursor_paginator(), "data_selector": "data"},
        child_endpoint_extra={
            "paginator": "single_page",
            # An order deleted after the list was read returns 404, so skip it.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        page_size_param=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
        resume_parent_pagination=True,
    )
    items = cast(Resource, resource).add_map(add_utm_columns)
    return _source_response(endpoint, config, items)


def samcart_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SamCartResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAMCART_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _orders_source(
            api_key,
            endpoint,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    rest_config: RESTAPIConfig = {
        "client": {**_client_config(api_key), "paginator": _cursor_paginator()},
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint.lower(),
                "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                if should_use_incremental_field
                else "replace",
                "endpoint": {
                    "path": config.path,
                    "params": _list_params(should_use_incremental_field, db_incremental_field_last_value),
                    "data_selector": "data",
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(SamCartResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(endpoint, config, resource)


def check_access(api_key: str) -> Optional[int]:
    """Probe one list endpoint with the API key. Returns the HTTP status, or None when SamCart is unreachable."""
    _, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}{PROBE_PATH}?limit=1",
        headers={"sc-api": api_key, "Accept": "application/json"},
        timeout=15,
        # The key rides in a custom header, which requests does not strip on a cross-origin redirect.
        allow_redirects=False,
    )
    return status
