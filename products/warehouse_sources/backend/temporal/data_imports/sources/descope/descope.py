import time
import hashlib
from collections.abc import Callable, Iterator
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.settings import (
    ANALYTICS_BUCKET,
    ANALYTICS_LOOKBACK_DAYS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    USER_INCREMENTAL_TIME_PARAMS,
)

DESCOPE_BASE_URL = "https://api.descope.com"
USERS_PAGE_SIZE = 100
DAY_MS = 24 * 60 * 60 * 1000
# The fan-out endpoints issue one request per parent, so a single stalled request would hang a
# whole sync with no progress. Bound each one instead.
REQUEST_TIMEOUT_SECONDS = 60


@frozen
class DescopeResumeConfig:
    # The `POST /v2/mgmt/user/search` page to pick back up at. `Users` and `UserHistory` both walk
    # that list, and each schema syncs under its own job id, so the two never read each other's
    # cursor. Every other endpoint returns its full result in one response, so there's nothing to
    # save between heartbeats.
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


def _analytics_body(now_ms: int) -> dict[str, Any]:
    # Group on every dimension the endpoint offers so the aggregate keeps its detail; grouping on
    # fewer would collapse rows we cannot split apart again. The official SDK sends `from` as epoch
    # milliseconds even though the published spec types it as a string.
    return {
        "from": now_ms - ANALYTICS_LOOKBACK_DAYS * DAY_MS,
        "groupByAction": True,
        "groupByDevice": True,
        "groupByMethod": True,
        "groupByGeo": True,
        "groupByTenant": True,
        "groupByReferrer": True,
        "groupByCreated": ANALYTICS_BUCKET,
    }


def _synthetic_row_id(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Synthesize a stable id for a response that carries no record id of its own.

    Deterministic across reruns: overlapping fetches merge onto the same row instead of
    duplicating it."""
    joined = "|".join("\x00" if row.get(field) is None else str(row.get(field)) for field in fields)
    row["id"] = hashlib.sha256(joined.encode()).hexdigest()
    return row


# Descope's audit search, authentication history and analytics aggregate all answer without a
# unique record id (verified against the published spec and both official SDKs' response types).
_AUDIT_ID_FIELDS = ("userId", "action", "occurred", "device", "method", "remoteAddress")
_USER_HISTORY_ID_FIELDS = ("userId", "loginTime", "ip", "city", "country", "selectedTenant")
_ANALYTICS_ID_FIELDS = ("created", "action", "device", "method", "geo", "tenant", "referrer")


def _audit_row_id(row: dict[str, Any]) -> dict[str, Any]:
    return _synthetic_row_id(row, _AUDIT_ID_FIELDS)


def _analytics_row_id(row: dict[str, Any]) -> dict[str, Any]:
    return _synthetic_row_id(row, _ANALYTICS_ID_FIELDS)


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

    if name == "Permissions":
        endpoint = {
            "path": "/v1/mgmt/permission/all",
            "paginator": SinglePagePaginator(),
            "data_selector": "permissions",
        }
        permissions_resource: EndpointResource = {
            "name": name,
            "table_name": "permissions",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }
        return permissions_resource

    if name == "Analytics":
        endpoint = {
            "path": "/v1/mgmt/analytics/search",
            "method": "POST",
            "json": _analytics_body(int(time.time() * 1000)),
            "paginator": SinglePagePaginator(),
            "data_selector": "analytics",
        }
        analytics_resource: EndpointResource = {
            "name": name,
            "table_name": "analytics",
            # The aggregate restates every bucket in the window on each sync, including buckets a
            # previous sync already wrote, so replacing the window is the only way counts stay
            # right. The endpoint takes a `from` filter but returns no cursor to resume from.
            "write_disposition": "replace",
            "endpoint": endpoint,
            "data_map": _analytics_row_id,
            "table_format": "delta",
        }
        return analytics_resource

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


def _client(project_id: str, management_key: str) -> RESTClient:
    return RESTClient(
        base_url=DESCOPE_BASE_URL,
        auth=BearerTokenAuth(token=bearer_token(project_id, management_key)),
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _tenant_ids(client: RESTClient) -> Iterator[str]:
    for page in client.paginate(
        path="/v1/mgmt/tenant/all",
        paginator=SinglePagePaginator(),
        data_selector="tenants",
    ):
        for tenant in page:
            tenant_id = tenant.get("id")
            if tenant_id:
                yield str(tenant_id)


def _groups_rows(project_id: str, management_key: str) -> Iterator[list[dict[str, Any]]]:
    """Every external group in the project, fanned out over the tenant list.

    Groups are only addressable per tenant, and each group already carries its members, so
    `/v1/mgmt/group/members` and `/v1/mgmt/group/member/all` would only re-return filtered views
    of these same rows.
    """
    client = _client(project_id, management_key)
    for tenant_id in _tenant_ids(client):
        for page in client.paginate(
            method="post",
            path="/v1/mgmt/group/all",
            json={"tenantId": tenant_id},
            paginator=SinglePagePaginator(),
            data_selector="groups",
        ):
            rows = [{**group, "tenantId": tenant_id} for group in page]
            if rows:
                yield rows


def _history_for_users(client: RESTClient, user_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in client.paginate(
        method="post",
        path="/v2/mgmt/user/history",
        json={"userIds": user_ids},
        paginator=SinglePagePaginator(),
        data_selector="usersAuthHistory",
    ):
        rows.extend(_synthetic_row_id(dict(row), _USER_HISTORY_ID_FIELDS) for row in page)
    return rows


def _user_history_rows(
    project_id: str,
    management_key: str,
    resumable_source_manager: ResumableSourceManager[DescopeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Authentication history for every user, one request per page of the user search.

    The endpoint takes the user ids it reports on, so the user list has to be walked first. It
    takes no timestamp filter, which is why this table is full refresh only.
    """
    client = _client(project_id, management_key)
    next_page = 0
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            next_page = resume.page

    for page in client.paginate(
        method="post",
        path="/v2/mgmt/user/search",
        json=_users_body(
            should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        ),
        paginator=PageNumberPaginator(base_page=0, page_param="page", param_location="json"),
        data_selector="users",
        initial_paginator_state={"page": next_page},
    ):
        user_ids = [str(user["userId"]) for user in page if user.get("userId")]
        next_page += 1
        if user_ids:
            rows = _history_for_users(client, user_ids)
            if rows:
                yield rows
        # Checkpoint the page just drained, so a resume starts at the one after it rather than
        # re-emitting history rows the pipeline has already written.
        resumable_source_manager.save_state(DescopeResumeConfig(page=next_page))


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
    # Groups and UserHistory bind their parent through the POST body, which the declarative
    # fan-out cannot express: it only resolves a parent field into the path or the query string.
    items: Callable[[], Any]
    if endpoint == "Groups":
        items = lambda: _groups_rows(project_id, management_key)
    elif endpoint == "UserHistory":
        items = lambda: _user_history_rows(project_id, management_key, resumable_source_manager)
    else:
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
        items = lambda: resource

    partition_key = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_mode="datetime" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
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
