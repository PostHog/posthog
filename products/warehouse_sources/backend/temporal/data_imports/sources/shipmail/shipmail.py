from datetime import datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.settings import SHIPMAIL_ENDPOINTS

SHIPMAIL_BASE_URL = "https://shipmail.to/api/v1"
REQUEST_TIMEOUT_SECONDS = 30.0


@frozen
class ShipmailResumeConfig:
    cursor: str | None = None


def _incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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
    params: dict[str, Any] = {"limit": 100}

    if (
        endpoint == "messages"
        and should_use_incremental_field
        and incremental_field == "updated_at"
        and db_incremental_field_last_value is not None
    ):
        params["updated_after"] = _incremental_value(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHIPMAIL_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "paginator": JSONResponseCursorPaginator(
                cursor_path="pagination.next_cursor",
                cursor_param="cursor",
            ),
            "session": make_tracked_session(redact_values=(api_key,), capture=False),
        },
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
        sort_mode="asc" if endpoint == "messages" else "desc",
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
