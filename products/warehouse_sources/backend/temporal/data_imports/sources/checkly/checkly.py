from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.settings import (
    API_VERSION,
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    RESULT_FIELDS,
    RESULT_HISTORY_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkly import (
    ChecklySourceConfig,
)


@frozen
class ChecklyResumeConfig:
    paginator_state: dict[str, Any]
    from_timestamp: int | None = None
    to_timestamp: int | None = None


def endpoint_path(name: str, api_version: str) -> str:
    if api_version != API_VERSION:
        raise ValueError("This Checkly API version is not supported. Reconnect the source with v2.")
    if name not in ENDPOINTS:
        raise ValueError(f"Unknown Checkly table: {name}")
    return ENDPOINTS[name].path.replace("{api_version}", api_version)


def validate_credentials(
    config: ChecklySourceConfig, schema_name: str | None, api_version: str
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown Checkly table: {schema_name}"
    name = schema_name or "checks"
    if name == "check_results":
        name = "checks"
    client = RESTClient(
        base_url=BASE_URL,
        headers={"X-Checkly-Account": config.account_id},
        auth=BearerTokenAuth(config.api_key),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10.0, 60.0),
    )
    try:
        next(
            client.paginate(
                path=endpoint_path(name, api_version),
                params={"limit": 1} if ENDPOINTS[name].paginated else {},
                data_selector="$",
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 403 and schema_name is None:
            return True, None
        if status is not None and status in AUTH_ERRORS:
            return False, AUTH_ERRORS[status]
        raise
    return True, None


_SAFE_FIELDS_BY_RESOURCE = {
    "checks": frozenset({"id", "name", "checkType", "groupId", "created_at"}),
    "check_groups": frozenset({"id", "name"}),
    "alert_channels": frozenset({"id", "type", "created_at"}),
}


def _project_safe_fields(name: str, row: dict[str, Any]) -> dict[str, Any]:
    allowed = _SAFE_FIELDS_BY_RESOURCE[name]
    return {key: value for key, value in row.items() if key in allowed}


def list_resource(name: str, api_version: str) -> EndpointResource:
    endpoint = ENDPOINTS[name]
    resource: EndpointResource = {
        "name": name,
        "endpoint": {
            "path": endpoint_path(name, api_version),
            "params": {"limit": PAGE_SIZE} if endpoint.paginated else {},
            "data_selector": "$[?(@.checkId)]" if name == "check_statuses" else "$",
            "paginator": PageNumberPaginator(base_page=1) if endpoint.paginated else SinglePagePaginator(),
        },
    }
    if name in _SAFE_FIELDS_BY_RESOURCE:
        resource["data_map"] = lambda row: _project_safe_fields(name, row)
    return resource


def checkly_source(
    config: ChecklySourceConfig,
    manager: ResumableSourceManager[ChecklyResumeConfig],
    inputs: SourceInputs,
) -> SourceResponse:
    name = inputs.schema_name
    api_version = inputs.api_version or API_VERSION
    path = endpoint_path(name, api_version)
    saved = manager.load_state() if manager.can_resume() else None
    from_timestamp: int | None = None
    to_timestamp: int | None = None
    if name == "check_results":
        to_timestamp = int(datetime.now(UTC).timestamp())
        from_timestamp = to_timestamp - RESULT_HISTORY_SECONDS
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
            if watermark is None:
                raise ValueError("The Checkly result timestamp is invalid. Reset this table and try again.")
            from_timestamp = max(from_timestamp, int(watermark.timestamp()))
        if saved is not None:
            from_timestamp = saved.from_timestamp
            to_timestamp = saved.to_timestamp
        resources: list[str | EndpointResource] = [
            list_resource("checks", api_version),
            {
                "name": name,
                "include_from_parent": ["id"],
                "data_map": rename_parent_fields("checks", {"id": "checkId"}),
                "columns": {"created_at": {"data_type": "timestamp"}},
                "endpoint": {
                    "path": path,
                    "params": {
                        "checkId": {"type": "resolve", "resource": "checks", "field": "id"},
                        "limit": PAGE_SIZE,
                        "resultType": "ALL",
                        "fields": RESULT_FIELDS,
                        "from": from_timestamp,
                        "to": to_timestamp,
                    },
                    "data_selector": "entries",
                    "data_selector_required": True,
                    "data_selector_empty_ok": True,
                    "paginator": {"type": "cursor", "cursor_path": "nextId", "cursor_param": "nextId"},
                },
            },
        ]
    else:
        resources = [list_resource(name, api_version)]

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                ChecklyResumeConfig(paginator_state=state, from_timestamp=from_timestamp, to_timestamp=to_timestamp)
            )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.api_key},
            "headers": {"X-Checkly-Account": config.account_id},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (10.0, 60.0),
        },
        "resources": resources,
    }
    resource = rest_api_resources(
        rest_config,
        team_id=inputs.team_id,
        job_id=inputs.job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=saved.paginator_state if saved else None,
    )[-1]

    def items() -> Iterator[list[dict[str, Any]]]:
        if name == "check_results" and from_timestamp is not None and to_timestamp is not None:
            if from_timestamp >= to_timestamp:
                return
        yield from resource

    return SourceResponse(
        name=name,
        items=items,
        primary_keys=list(ENDPOINTS[name].primary_keys),
        column_hints=resource.column_hints,
        partition_keys=["created_at"] if name == "check_results" else None,
        partition_mode="datetime" if name == "check_results" else None,
        partition_format="day" if name == "check_results" else None,
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
