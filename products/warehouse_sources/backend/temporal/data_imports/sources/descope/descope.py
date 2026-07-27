import hashlib
import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.settings import (
    PARTITION_KEYS,
    PRIMARY_KEYS,
    USER_INCREMENTAL_TIME_PARAMS,
)

DESCOPE_BASE_URL = "https://api.descope.com"
USERS_PAGE_SIZE = 100


@dataclasses.dataclass
class DescopeResumeConfig:
    # Only the paginated `Users` endpoint resumes mid-sync; every other endpoint returns its
    # full result in one response, so there's nothing to save between heartbeats.
    page: int


def bearer_token(project_id: str, management_key: str) -> str:
    return f"{project_id}:{management_key}"


def _users_body(
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    # Sort on whichever field drives incrementality (falling back to createdTime for full
    # refresh) so pages stay stable and the watermark advances monotonically.
    sort_field = incremental_field if incremental_field in USER_INCREMENTAL_TIME_PARAMS else "createdTime"
    body: dict[str, Any] = {
        "limit": USERS_PAGE_SIZE,
        "sort": [{"field": sort_field, "desc": False}],
    }
    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        param_name = USER_INCREMENTAL_TIME_PARAMS.get(incremental_field)
        if param_name:
            body[param_name] = int(db_incremental_field_last_value)
    return body


def _audit_body(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        body["from"] = int(db_incremental_field_last_value)
    return body


def _audit_row_id(row: dict[str, Any]) -> dict[str, Any]:
    """Descope's audit search response carries no unique record id, so synthesize a stable one
    from the event's identity fields. Deterministic across reruns: overlapping incremental
    fetches merge onto the same row instead of duplicating it."""
    parts = (
        row.get("userId"),
        row.get("action"),
        row.get("occurred"),
        row.get("device"),
        row.get("method"),
        row.get("remoteAddress"),
    )
    joined = "|".join("\x00" if part is None else str(part) for part in parts)
    row["id"] = hashlib.sha256(joined.encode()).hexdigest()
    return row


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Any,
) -> EndpointResource:
    write_disposition = {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"

    if name == "Users":
        endpoint: Endpoint = {
            "path": "/v2/mgmt/user/search",
            "method": "POST",
            "json": _users_body(should_use_incremental_field, incremental_field, db_incremental_field_last_value),
            "paginator": PageNumberPaginator(base_page=0, page_param="page", param_location="json"),
            "data_selector": "users",
        }
        users_resource: EndpointResource = {
            "name": name,
            "table_name": "users",
            "write_disposition": write_disposition,
            "endpoint": endpoint,
            "table_format": "delta",
        }
        return users_resource

    if name == "Audit":
        endpoint = {
            "path": "/v1/mgmt/audit/search",
            "method": "POST",
            "json": _audit_body(should_use_incremental_field, db_incremental_field_last_value),
            "paginator": SinglePagePaginator(),
            "data_selector": "audits",
        }
        audit_resource: EndpointResource = {
            "name": name,
            "table_name": "audit",
            "write_disposition": write_disposition,
            "endpoint": endpoint,
            "data_map": _audit_row_id,
            "table_format": "delta",
        }
        return audit_resource

    if name == "Tenants":
        endpoint = {
            "path": "/v1/mgmt/tenant/all",
            "paginator": SinglePagePaginator(),
            "data_selector": "tenants",
        }
        tenants_resource: EndpointResource = {
            "name": name,
            "table_name": "tenants",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }
        return tenants_resource

    if name == "Roles":
        endpoint = {
            "path": "/v1/mgmt/role/search",
            "method": "POST",
            "json": {},
            "paginator": SinglePagePaginator(),
            "data_selector": "roles",
        }
        roles_resource: EndpointResource = {
            "name": name,
            "table_name": "roles",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }
        return roles_resource

    if name == "AccessKeys":
        endpoint = {
            "path": "/v1/mgmt/accesskey/search",
            "method": "POST",
            "json": {"tenantIds": []},
            "paginator": SinglePagePaginator(),
            "data_selector": "keys",
        }
        access_keys_resource: EndpointResource = {
            "name": name,
            "table_name": "access_keys",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }
        return access_keys_resource

    raise ValueError(f"Unknown Descope endpoint: {name}")


def descope_source(
    project_id: str,
    management_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DescopeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    resource_config = get_resource(
        endpoint, should_use_incremental_field, incremental_field, db_incremental_field_last_value
    )

    config: RESTAPIConfig = {
        "client": {
            "base_url": DESCOPE_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": bearer_token(project_id, management_key),
            },
        },
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if endpoint == "Users" and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only Users paginates; other endpoints never call this (SinglePagePaginator never
        # reports a resume state), so this is a no-op for them.
        if endpoint != "Users" or not state:
            return
        page = state.get("page")
        if page is not None:
            resumable_source_manager.save_state(DescopeResumeConfig(page=int(page)))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_mode="datetime",
        partition_keys=[PARTITION_KEYS[endpoint]],
        sort_mode="asc",
    )


def validate_credentials(project_id: str, management_key: str) -> bool:
    token = bearer_token(project_id, management_key)
    session = make_tracked_session(redact_values=(management_key, token))
    response = session.post(
        f"{DESCOPE_BASE_URL}/v1/mgmt/projects/list",
        json={},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    return response.status_code == 200
