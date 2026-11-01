from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    FanoutEndpointLike,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevenshifts import (
    SevenShiftsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    BASE_URL,
    COMPANY_ERROR,
    DATE_ONLY_ENDPOINTS,
    ENDPOINTS,
    LOCATION_ENDPOINT_CONFIGS,
    LOCATION_ENDPOINTS,
    LOCATION_FANOUT,
    LOCATION_PRIMARY_KEYS,
)


@frozen
class SevenShiftsResumeConfig:
    cursor: str | None = None
    fanout_state: dict[str, Any] | None = None


def company_path(company_id: str) -> str:
    if not company_id.isascii() or not company_id.isdecimal() or int(company_id) <= 0:
        raise ValueError(COMPANY_ERROR)
    return f"company/{int(company_id)}"


def validate_credentials(config: SevenShiftsSourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        path = company_path(config.company_id)
    except ValueError:
        return False, COMPANY_ERROR

    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(config.access_token),
        headers={"x-api-version": api_version},
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    try:
        next(client.paginate(f"{path}/locations", params={"limit": 1}, data_selector="data"))
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, ACCESS_ERROR
            if error.response.status_code == 404:
                return False, "7shifts could not find this company. Check the company ID."
        raise
    return True, None


def _client_config(config: SevenShiftsSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": config.access_token},
        "headers": {"x-api-version": api_version},
        "paginator": {
            "type": "cursor",
            "cursor_path": "meta.cursor.next",
            "cursor_param": "cursor",
            "raise_on_repeated_cursor": True,
        },
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 30,
    }


def _location_source(
    config: SevenShiftsSourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[SevenShiftsResumeConfig],
) -> SourceResponse:
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            manager.save_state(SevenShiftsResumeConfig(fanout_state=state))

    data_selector: Endpoint = {"data_selector": "data", "data_selector_required": True}
    resource = build_dependent_resource(
        endpoint_configs=cast(Mapping[str, FanoutEndpointLike], LOCATION_ENDPOINT_CONFIGS),
        child_endpoint=endpoint,
        fanout=LOCATION_FANOUT,
        client_config=_client_config(config, api_version),
        path_format_values={"company": company_path(config.company_id)},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra=data_selector,
        child_endpoint_extra=data_selector,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout_state if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=LOCATION_PRIMARY_KEYS,
        on_complete=manager.clear_state,
    )


def sevenshifts_source(
    config: SevenShiftsSourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[SevenShiftsResumeConfig],
    should_use_incremental_field: bool,
    last_value: datetime | str | None,
) -> SourceResponse:
    schema_for_resource(dict.fromkeys(ENDPOINTS), endpoint)
    if endpoint in LOCATION_ENDPOINTS:
        return _location_source(config, endpoint, api_version, team_id, job_id, manager)

    params: dict[str, Any] = {"limit": 100}
    if endpoint == "shifts":
        params["include_deleted"] = "true"
    if should_use_incremental_field and last_value is not None:
        watermark = datetime.fromisoformat(last_value) if isinstance(last_value, str) else last_value
        watermark = watermark.replace(tzinfo=UTC) if watermark.tzinfo is None else watermark.astimezone(UTC)
        # Overlap the boundary because modified_since can exclude records at the exact cutoff.
        params["modified_since"] = (
            (watermark - timedelta(days=1)).date().isoformat()
            if endpoint in DATE_ONLY_ENDPOINTS
            else (watermark - timedelta(seconds=1)).isoformat()
        )

    endpoint_config: Endpoint = {
        "path": f"{company_path(config.company_id)}/{endpoint}",
        "params": params,
        "data_selector": "data",
        "data_selector_required": True,
    }
    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    rest_config: RESTAPIConfig = {
        "client": _client_config(config, api_version),
        "resources": [resource_config],
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and state.get("cursor") is not None:
            manager.save_state(SevenShiftsResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume and resume.cursor else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        # The API does not guarantee ascending modified timestamps, so checkpoint only after the full scan.
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
