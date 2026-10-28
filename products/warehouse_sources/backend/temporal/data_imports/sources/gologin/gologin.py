from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_chained_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.settings import (
    AUTH_ERROR,
    BASE_URL,
    CLOUD_USAGE_MAX_DAYS,
    ENDPOINTS,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
    REQUEST_TIMEOUT,
    WORKSPACE_ENDPOINTS,
)


@frozen
class GoLoginResumeConfig:
    page: int


class DeletedProfilesPaginator(BasePaginator):
    """Advances `offset` by the rows received until GoLogin reports no more deleted profiles."""

    def __init__(self) -> None:
        super().__init__()
        self.offset = 0

    def init_request(self, request: Request) -> None:
        request.params = {**(request.params or {}), "offset": self.offset}

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        received = len(data or [])
        self.offset += received
        self._has_next_page = received > 0 and response.json().get("isMoreDeletedProfilesAvailable") is True

    def update_request(self, request: Request) -> None:
        request.params = {**(request.params or {}), "offset": self.offset}


def cloud_usage_days(should_use_incremental_field: bool, db_incremental_field_last_value: Any, today: date) -> int:
    if should_use_incremental_field:
        last_value = parse_datetime_value(db_incremental_field_last_value)
        if last_value is not None:
            # Re-read the watermark day, because it was still in progress when it last synced.
            return min(max((today - last_value.date()).days + 1, 1), CLOUD_USAGE_MAX_DAYS)
    return CLOUD_USAGE_MAX_DAYS


def _normalize_tag(row: dict[str, Any]) -> dict[str, Any]:
    if "id" not in row and "_id" in row:
        row["id"] = row.pop("_id")
    return row


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
    )
    try:
        next(client.paginate("/user", data_selector="$"))
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise
    return True, None


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
    }


def _workspace_child_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Any:
    params: dict[str, Any] = {"workspace_id": {"type": "resolve", "resource": "workspaces", "field": "id"}}
    if endpoint == "cloud_usage_daily":
        params["days"] = cloud_usage_days(
            should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC).date()
        )
    child_endpoint: Endpoint = {**WORKSPACE_ENDPOINTS[endpoint], "params": params}
    if endpoint == "deleted_profiles":
        child_endpoint["paginator"] = DeletedProfilesPaginator()

    parent: EndpointResource = {
        "name": "workspaces",
        "table_name": "workspaces",
        "write_disposition": "replace",
        "endpoint": Endpoint(**ENDPOINTS["workspaces"]),
        "table_format": "delta",
    }
    child: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": (
            {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"
        ),
        "include_from_parent": ["id"],
        "endpoint": child_endpoint,
        "table_format": "delta",
    }
    if endpoint == "tags":
        # GoLogin returns a tag id as `_id` or as `id`.
        child["data_map"] = _normalize_tag

    return build_chained_resource(
        resources=[parent, child],
        child_name=endpoint,
        parent_name="workspaces",
        parent_field_renames={"id": "workspace_id"},
        client_config=_client_config(api_key),
        team_id=team_id,
        job_id=job_id,
    )


def gologin_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GoLoginResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if endpoint in WORKSPACE_ENDPOINTS:
        resource = _workspace_child_resource(
            api_key, endpoint, team_id, job_id, should_use_incremental_field, db_incremental_field_last_value
        )
        return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=PRIMARY_KEYS[endpoint])

    endpoint_config = ENDPOINTS[endpoint]
    initial_state: dict[str, Any] | None = None
    if endpoint == "profiles" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"page": resume.page}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and "page" in state:
            resumable_source_manager.save_state(GoLoginResumeConfig(page=int(state["page"])))

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [{"name": endpoint, "endpoint": endpoint_config, "write_disposition": "replace"}],
    }
    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=["id"])
