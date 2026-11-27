from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.retell_ai.settings import (
    BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGE_SIZE,
    RetellAIEndpoint,
    RetellAIParent,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceInputs,
    SourceResponse,
    frozen,
    make_tracked_session,
    parse_datetime_value,
    rest_api_resource,
    schema_for_resource,
)


@frozen
class RetellAIResumeConfig:
    cursor: str | None = None
    completed: bool = False


class RetellAIPaginator(JSONResponseCursorPaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("has_more"), bool):
            raise ValueError("Unexpected Retell AI pagination response: missing has_more")
        # The terminal response can still carry a cursor. Only has_more authorizes another request.
        if not body["has_more"]:
            self._has_next_page = False
            return
        cursor = body.get("pagination_key")
        if not isinstance(cursor, str) or not cursor or cursor == self._cursor_value:
            raise ValueError("Unexpected Retell AI pagination response: missing or repeated cursor")
        super().update_state(response, data)


def _paginator(location: Literal["query", "json"]) -> RetellAIPaginator:
    return RetellAIPaginator(cursor_path="pagination_key", cursor_param="pagination_key", param_location=location)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 60),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _normalize_timestamps(row: dict[str, Any]) -> dict[str, Any]:
    # The pipeline's datetime partitions and lookback use seconds, while Retell returns epoch milliseconds.
    for field in ("start_timestamp", "end_timestamp"):
        value = row.get(field)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[field] = datetime.fromtimestamp(value / 1000, UTC)
    return row


def _normalize_call(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("access_token", None)
    return _normalize_timestamps(row)


def _root_listing(settings: RetellAIEndpoint) -> tuple[str, Literal["GET", "POST"]]:
    parent = settings.parents[0]
    while parent.table is not None:
        parent = ENDPOINTS[parent.table].parents[0]
    if parent.path is None:
        raise ValueError("Retell AI fan-out parent has neither a path nor a table")
    return parent.path, parent.method


def get_resource(
    name: str,
    api_version: str,
    should_use_incremental_field: bool = False,
    watermark: object = None,
    *,
    probe: bool = False,
) -> EndpointResource:
    settings = schema_for_resource(ENDPOINTS, name)
    # A fan-out table has no listing of its own, so it reads (and probes) its first root parent listing.
    path, method = _root_listing(settings) if settings.parents else (settings.path, settings.method)
    endpoint: Endpoint = {"path": path.format(api_version=api_version), "method": method}
    if settings.paginated:
        endpoint["data_selector"] = "items"
        endpoint["data_selector_required"] = True
        endpoint["paginator"] = "single_page" if probe else _paginator(settings.pagination_location)
        sort_order = "ascending" if settings.parents else settings.sort_order
        pagination: dict[str, Any] = {"limit": 1 if probe else PAGE_SIZE, "sort_order": sort_order}
        if settings.pagination_location == "json":
            if should_use_incremental_field and name in INCREMENTAL_FIELDS and watermark is not None:
                timestamp = parse_datetime_value(watermark)
                if timestamp is None:
                    raise ValueError("Invalid Retell AI start_timestamp watermark")
                pagination["filter_criteria"] = {
                    "start_timestamp": {"type": "number", "op": "ge", "value": int(timestamp.timestamp() * 1000)}
                }
            endpoint["json"] = pagination
        else:
            endpoint["params"] = pagination
    else:
        endpoint["paginator"] = "single_page"

    resource: EndpointResource = {"name": name, "endpoint": endpoint, "primary_key": settings.primary_keys}
    if name == "calls":
        resource["data_map"] = _normalize_call
    elif name in INCREMENTAL_FIELDS:
        resource["data_map"] = _normalize_timestamps
    return resource


def _parent_resource(path: str, parent: RetellAIParent) -> EndpointResource:
    return {
        "name": path,
        "endpoint": {
            "path": path,
            "method": parent.method,
            "params": {"limit": PAGE_SIZE, "sort_order": "ascending"},
            "data_selector": "items",
            "data_selector_required": True,
            "paginator": _paginator("query"),
        },
    }


def _child_resource(
    name: str, settings: RetellAIEndpoint, parent: RetellAIParent, parent_id: str, version: str | None
) -> EndpointResource:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if settings.sortable:
        params["sort_order"] = "ascending"
    for key, value in parent.child_params:
        if "{version}" in value:
            if version is None:
                continue
            value = value.replace("{version}", version)
        params[key] = value.replace("{id}", parent_id)
    resource: EndpointResource = {
        "name": name,
        "endpoint": {
            "path": settings.path.replace("{id}", quote(parent_id, safe="")),
            "method": settings.method,
            "params": params,
            "data_selector": "items",
            "data_selector_required": True,
            "paginator": _paginator("query"),
            # A parent deleted between the parent listing and this request has no children left to read.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "primary_key": settings.primary_keys,
    }
    if settings.include_parent_id:
        resource["data_map"] = lambda row: {**row, parent.id_field: parent_id}
    return resource


def _parent_version(parent: RetellAIParent, row: dict[str, Any]) -> str | None:
    if parent.version_field is None:
        return None
    value = row.get(parent.version_field)
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _parent_pages(
    client: ClientConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[RetellAIResumeConfig],
    parent: RetellAIParent,
) -> Iterator[list[dict[str, Any]]]:
    if parent.table is not None:
        return _fan_out_pages(client, inputs, manager, parent.table)
    if parent.path is None:
        raise ValueError("Retell AI fan-out parent has neither a path nor a table")
    config: RESTAPIConfig = {"client": client, "resources": [_parent_resource(parent.path, parent)]}
    return iter(rest_api_resource(config, inputs.team_id, inputs.job_id, None))


def _fan_out_pages(
    client: ClientConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[RetellAIResumeConfig],
    name: str,
) -> Iterator[list[dict[str, Any]]]:
    settings = ENDPOINTS[name]
    for parent in settings.parents:
        # Parent listings can return one row per version of the same parent.
        seen: set[tuple[str, str | None]] = set()
        for parent_page in _parent_pages(client, inputs, manager, parent):
            for parent_row in parent_page:
                parent_id = parent_row.get(parent.id_field)
                if not isinstance(parent_id, str) or not parent_id:
                    continue
                version = _parent_version(parent, parent_row)
                if (parent_id, version) in seen:
                    continue
                seen.add((parent_id, version))
                child_config: RESTAPIConfig = {
                    "client": client,
                    "resources": [_child_resource(name, settings, parent, parent_id, version)],
                }
                yield from rest_api_resource(child_config, inputs.team_id, inputs.job_id, None)
                manager.safe_point()
            manager.safe_point()


def _fan_out(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[RetellAIResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # One session for every parent and child request, so the fan-out reuses its connections.
    client: ClientConfig = {
        **_client_config(api_key),
        "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False),
    }
    yield from _fan_out_pages(client, inputs, manager, inputs.schema_name)


def validate_credentials(api_key: str, schema_name: str | None, api_version: str) -> tuple[bool, str | None]:
    if not api_key or not api_key.isascii() or any(character.isspace() for character in api_key):
        return False, "Enter a valid Retell AI API key without spaces."
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [get_resource(schema_name or "calls", api_version, probe=True)],
    }
    try:
        list(rest_api_resource(config, team_id=0, job_id="", db_incremental_field_last_value=None))
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "Your Retell AI API key is invalid or expired. Create a new key and reconnect."
        if status == 403:
            if schema_name is None:
                return True, None
            return False, "Your Retell AI API key cannot read this table. Check its permissions and reconnect."
        raise
    return True, None


def retell_ai_source(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[RetellAIResumeConfig],
    api_version: str,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)
    if settings.parents:
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: _fan_out(api_key, inputs, manager),
            primary_keys=settings.primary_keys,
            supports_resume=False,
        )
    resume = manager.load_state() if settings.paginated and manager.can_resume() else None

    def save_state(state: dict[str, Any] | None) -> None:
        manager.save_state(RetellAIResumeConfig(cursor=state["cursor"] if state else None, completed=state is None))

    def items() -> Iterator[list[dict[str, Any]]]:
        if resume is not None and resume.completed:
            return
        config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resources": [
                get_resource(
                    inputs.schema_name,
                    api_version,
                    inputs.should_use_incremental_field,
                    inputs.db_incremental_field_last_value,
                )
            ],
        }
        yield from rest_api_resource(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_state if settings.paginated else None,
            initial_paginator_state={"cursor": resume.cursor} if resume is not None and resume.cursor else None,
        )

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=settings.primary_keys,
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        sort_mode="asc",
        supports_resume=settings.paginated,
    )
