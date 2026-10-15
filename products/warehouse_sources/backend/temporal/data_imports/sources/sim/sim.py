import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sim import SimSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.settings import (
    ENDPOINTS,
    PARENT_ENDPOINTS,
    USAGE_WINDOW_DAYS,
    SimEndpoint,
)

# Page size for listing organizations while validating usage access.
USAGE_PROBE_ORGANIZATIONS = 10

AUTH_ERROR = "Your Sim API key is invalid or expired. Create a new key in Sim settings and reconnect."
PERMISSION_ERROR = "Your Sim API key cannot read this workspace. Check the key's workspace access and permissions."
WORKSPACE_ERROR = "Sim could not find this workspace. Check the workspace ID and your API key's access."
USAGE_PERMISSION_ERROR = (
    "Sim usage events need a personal API key from an organization admin. Workspace API keys cannot read them."
)

ALL_ENDPOINTS: dict[str, SimEndpoint] = {**ENDPOINTS, **PARENT_ENDPOINTS}
PAGE_EXTRA: Endpoint = {
    "data_selector": "data",
    "data_selector_required": True,
    "paginator": {"type": "cursor", "cursor_path": "nextCursor", "cursor_param": "cursor"},
}


@frozen
class SimResumeConfig:
    cursor: str | None = None
    fanout_state: dict[str, Any] | None = None
    # A usage cursor is only valid for the window it was issued for, so a resumed run reuses that window.
    start_date: str | None = None
    end_date: str | None = None


def client_config(config: SimSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://www.sim.ai/api/{api_version}/",
        "auth": {"type": "api_key", "name": "X-API-Key", "api_key": config.api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 60),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def endpoint_filters(config: SimSourceConfig, endpoint: SimEndpoint) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if endpoint.workspace_scoped:
        params["workspaceId"] = config.workspace_id
    if endpoint.sort_field:
        params["sortBy"] = endpoint.sort_field
        params["sortOrder"] = "asc"
    return params


def get_endpoint(config: SimSourceConfig, name: str, page_size: int | None = None) -> Endpoint:
    endpoint = schema_for_resource(ALL_ENDPOINTS, name)
    return {
        "path": endpoint.path,
        "params": {"limit": page_size or endpoint.page_size, **endpoint_filters(config, endpoint)},
        **PAGE_EXTRA,
    }


def get_resource(config: SimSourceConfig, name: str) -> EndpointResource:
    return {
        "name": name,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": get_endpoint(config, name),
    }


@frozen
class UsageWindow:
    start: str
    end: str


def usage_window(inputs: SourceInputs, resume: SimResumeConfig | None) -> UsageWindow:
    if resume is not None and resume.start_date and resume.end_date:
        return UsageWindow(start=resume.start_date, end=resume.end_date)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=USAGE_WINDOW_DAYS)
    last_value = parse_datetime_value(inputs.db_incremental_field_last_value)
    if inputs.should_use_incremental_field and last_value is not None:
        if last_value.date() < start:
            inputs.logger.warning(
                "Sim usage watermark is older than the longest window Sim serves; older events are skipped",
                watermark=last_value.isoformat(),
                window_start=start.isoformat(),
            )
        start = min(max(start, last_value.date()), end)
    return UsageWindow(start=start.isoformat(), end=end.isoformat())


def _check_usage_access(
    client: RESTClient, endpoint: SimEndpoint, organization_pages: Iterator[Any]
) -> tuple[bool, str | None]:
    # Listing organizations succeeds for any key, but usage needs organization admin rights in at least one of them.
    end = datetime.now(UTC).date()
    start = end - timedelta(days=1)
    found_organization = False
    for page in organization_pages:
        for organization in page:
            if not organization.get("id"):
                continue
            found_organization = True
            try:
                next(
                    client.paginate(
                        path=endpoint.path.format(organization_id=organization["id"]),
                        params={
                            "limit": 1,
                            "preset": "custom",
                            "startDate": start.isoformat(),
                            "endDate": end.isoformat(),
                        },
                        data_selector="data",
                        data_selector_required=True,
                    )
                )
            except HTTPError as error:
                if error.response is not None and error.response.status_code in (403, 404):
                    continue
                raise
            return True, None
    # A key without organizations has no usage to read, so there is nothing to reject.
    return (False, USAGE_PERMISSION_ERROR) if found_organization else (True, None)


def validate_credentials(
    config: SimSourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    endpoint = schema_for_resource(ENDPOINTS, schema_name or "workflows")
    # A fan-out table is readable when its parent list is, because the parent ids drive every child request.
    probe_name = endpoint.fanout.parent_name if endpoint.fanout else endpoint.name
    is_usage = endpoint.name == "usage_events"
    probe = get_endpoint(config, probe_name, page_size=USAGE_PROBE_ORGANIZATIONS if is_usage else 1)
    client_settings = client_config(config, api_version)
    client = RESTClient(
        base_url=client_settings["base_url"],
        auth=create_auth(client_settings["auth"]),
        headers=client_settings["headers"],
        request_timeout=client_settings["request_timeout"],
        allowed_hosts=[],
        allow_redirects=False,
    )
    try:
        pages = client.paginate(
            path=cast(str, probe["path"]),
            params=probe["params"],
            paginator=JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor")
            if is_usage
            else None,
            data_selector="data",
            data_selector_required=True,
        )
        if is_usage:
            return _check_usage_access(client, endpoint, pages)
        next(pages)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            if schema_name is None:
                return True, None
            return False, USAGE_PERMISSION_ERROR if endpoint.name == "usage_events" else PERMISSION_ERROR
        if status == 404:
            return False, WORKSPACE_ERROR
        raise
    finally:
        client.session.close()
    return True, None


def sim_source(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state() if manager.can_resume() else None
    window: UsageWindow | None = None

    resource: Iterable[Any]
    if endpoint.fanout is None:

        def save_checkpoint(state: dict[str, Any] | None) -> None:
            if state and state.get("cursor"):
                manager.save_state(SimResumeConfig(cursor=str(state["cursor"])))

        resource_config: RESTAPIConfig = {
            "client": client_config(config, api_version),
            "resources": [get_resource(config, inputs.schema_name)],
        }
        resource = rest_api_resource(
            resource_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": resume.cursor} if resume is not None and resume.cursor else None,
        )
    else:
        child_params = endpoint_filters(config, endpoint)
        if endpoint.name == "usage_events":
            window = usage_window(inputs, resume)
            child_params.update(preset="custom", startDate=window.start, endDate=window.end)

        def save_fanout_checkpoint(state: dict[str, Any] | None) -> None:
            manager.save_state(
                SimResumeConfig(
                    fanout_state=state,
                    start_date=window.start if window else None,
                    end_date=window.end if window else None,
                )
            )

        parent = ALL_ENDPOINTS[endpoint.fanout.parent_name]
        resource = build_dependent_resource(
            endpoint_configs=ALL_ENDPOINTS,
            child_endpoint=endpoint.name,
            fanout=dataclasses.replace(
                endpoint.fanout, parent_params=endpoint_filters(config, parent), child_params=child_params
            ),
            client_config=client_config(config, api_version),
            path_format_values={},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=PAGE_EXTRA,
            child_endpoint_extra=PAGE_EXTRA,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume is not None else None,
        )

    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
    )
