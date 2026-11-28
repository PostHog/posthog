from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    JSONResponseCursorPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.shipmail.settings import SHIPMAIL_ENDPOINTS

SHIPMAIL_BASE_URL = "https://shipmail.to/api/v1"
REQUEST_TIMEOUT_SECONDS = 30.0


@frozen
class ShipmailResumeConfig:
    cursor: str | None = None
    fanout_state: dict[str, Any] | None = None


def _incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _drop_repeated_rows(
    scope_field: str, primary_keys: list[str]
) -> Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]:
    # The fan-out finishes one parent before the next, so the seen keys only need to cover one scope.
    scope: list[Any] = [None]
    seen: set[tuple[Any, ...]] = set()

    def drop(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        if row.get(scope_field) != scope[0]:
            scope[0] = row.get(scope_field)
            seen.clear()
        key = tuple(row.get(field) for field in primary_keys)
        if key in seen:
            return []
        seen.add(key)
        return row

    return drop


def _initial_paginator_state(
    resumable_source_manager: ResumableSourceManager[ShipmailResumeConfig],
) -> dict[str, str] | None:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    if resume is None or resume.cursor is None:
        return None
    return {"cursor": resume.cursor}


def shipmail_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShipmailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = SHIPMAIL_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"limit": endpoint_config.page_size}

    if (
        endpoint == "messages"
        and should_use_incremental_field
        and incremental_field == "updated_at"
        and db_incremental_field_last_value is not None
    ):
        params["updated_after"] = _incremental_value(db_incremental_field_last_value)

    client_config: ClientConfig = {
        "base_url": SHIPMAIL_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
        "paginator": JSONResponseCursorPaginator(
            cursor_path="pagination.next_cursor",
            cursor_param="cursor",
        ),
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
    }
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": params,
                    "data_selector": "data",
                    "data_selector_required": True,
                },
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ShipmailResumeConfig(cursor=str(state["cursor"])))

    resource: Iterable[Any]
    if endpoint_config.fanout is not None:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        def save_fanout_checkpoint(state: dict[str, Any] | None) -> None:
            if state is not None:
                resumable_source_manager.save_state(ShipmailResumeConfig(fanout_state=state))

        resource = build_dependent_resource(
            endpoint_configs=SHIPMAIL_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": "data", "data_selector_required": True},
            child_endpoint_extra={
                "data_selector": "data",
                "data_selector_required": True,
                "paginator": JSONResponseCursorPaginator(cursor_path="pagination.next_cursor", cursor_param="cursor"),
            },
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
            resume_parent_pagination=True,
        )
        if endpoint_config.drop_repeated_rows_per is not None and isinstance(resource, Resource):
            resource.add_map(_drop_repeated_rows(endpoint_config.drop_repeated_rows_per, endpoint_config.primary_keys))
    else:
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=_initial_paginator_state(resumable_source_manager),
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        sort_mode=endpoint_config.sort_mode,
    )


def get_capabilities(api_key: str) -> tuple[int | None, set[str]]:
    try:
        session = make_tracked_session(redact_values=(api_key,), capture=False)
        response = session.get(
            f"{SHIPMAIL_BASE_URL}/capabilities",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            return response.status_code, set()
        body = response.json()
        scopes = body.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            return response.status_code, set()
        return response.status_code, {scope for scope in scopes if isinstance(scope, str)}
    except Exception:  # noqa: BLE001 - credential probes must return a validation result, never raise
        return None, set()
