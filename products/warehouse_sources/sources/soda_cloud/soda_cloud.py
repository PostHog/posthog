from datetime import datetime
from typing import Any, cast

from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    PageNumberPaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sodacloud import (
    SodaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGE_SIZE,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
    REGION_ERROR,
    REGIONS,
)


@frozen
class SodaCloudResumeConfig:
    page: int
    from_datetime: str | None = None


def get_base_url(region: str, api_version: str) -> str:
    if region not in REGIONS:
        raise ValueError(REGION_ERROR)
    if api_version != "v1":
        raise ValueError("Unsupported Soda Cloud API version.")
    return f"{REGIONS[region]}/api/{api_version}/"


def validate_credentials(config: SodaCloudSourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        base_url = get_base_url(config.region, api_version)
    except ValueError as error:
        return False, str(error)

    with make_tracked_session(redact_values=(config.api_key_id, config.api_key_secret)) as session:
        try:
            response = session.get(
                f"{base_url}datasets",
                auth=HttpBasicAuth(config.api_key_id, config.api_key_secret),
                params={"page": 0, "size": 10},
                timeout=(10, 30),
                allow_redirects=False,
            )
        except RequestException:
            return False, "Could not connect to Soda Cloud. Check the region and try again."

    if response.status_code == 401:
        return False, AUTH_ERROR
    if response.status_code == 403:
        return False, PERMISSION_ERROR
    if response.status_code != 200:
        return False, "Could not validate the Soda Cloud API keys. Try again later."
    return True, None


def soda_cloud_source(
    config: SodaCloudSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SodaCloudResumeConfig],
    api_version: str,
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError("Unsupported Soda Cloud table.")

    incremental = inputs.should_use_incremental_field and inputs.schema_name in INCREMENTAL_FIELDS
    from_datetime: str | None = None
    if incremental and inputs.db_incremental_field_last_value is not None:
        watermark = inputs.db_incremental_field_last_value
        from_datetime = watermark.isoformat() if isinstance(watermark, datetime) else str(watermark)

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None:
        # Page numbers must retain the original filter when a retry has a newer watermark.
        from_datetime = resume.from_datetime

    params: dict[str, str | int] = {"size": PAGE_SIZE}
    if incremental and from_datetime is not None:
        params["from"] = from_datetime

    paginator = cast(
        PageNumberPaginatorConfig,
        {"type": "page_number", "base_page": 0, "total_path": "totalPages"},
    )
    endpoint: Endpoint = {"path": inputs.schema_name, "data_selector": "content", "params": cast(Any, params)}
    resource_config: EndpointResource = {"name": inputs.schema_name, "endpoint": endpoint}
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(config.region, api_version),
            "auth": {"type": "http_basic", "username": config.api_key_id, "password": config.api_key_secret},
            "paginator": paginator,
            "allow_redirects": False,
            "request_timeout": (10, 60),
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(SodaCloudResumeConfig(page=int(state["page"]), from_datetime=from_datetime))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page} if resume is not None else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        # Datasets are ordered by name, so the pipeline must inspect every timestamp.
        sort_mode="desc",
    )
