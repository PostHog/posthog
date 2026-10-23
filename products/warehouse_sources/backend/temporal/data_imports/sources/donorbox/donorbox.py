from datetime import date, datetime, timedelta
from typing import Any, cast

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.settings import (
    ACCESS_ERROR,
    API_BASE_URL,
    API_VERSION,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGE_SIZE,
    PARTITION_SIZE,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.donorbox import (
    DonorboxSourceConfig,
)


@frozen
class DonorboxResumeConfig:
    page: int
    date_from: str | None = None


def validate_credentials(
    config: DonorboxSourceConfig, schema_name: str | None = None, api_version: str = API_VERSION
) -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, schema_name or "campaigns")
    client = RESTClient(
        base_url=f"{API_BASE_URL}{api_version}/",
        auth=HttpBasicAuth(username=config.email, password=config.api_key),
        paginator=SinglePagePaginator(),
        request_timeout=30,
    )
    try:
        next(client.paginate(path, params={"per_page": 1}, data_selector_required=True))
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, ACCESS_ERROR
        raise
    finally:
        client.session.close()
    return True, None


def donorbox_source(
    config: DonorboxSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DonorboxResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: datetime | date | str | None,
    api_version: str = API_VERSION,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    date_from = None
    if endpoint in INCREMENTAL_FIELDS and should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark_date = date.fromisoformat(str(db_incremental_field_last_value)[:10])
        # Date filters have no documented boundary semantics, so re-read the previous day too.
        date_from = (watermark_date - timedelta(days=1)).isoformat()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        # A saved page belongs to its original date window, even if the pipeline watermark moved.
        date_from = resume.date_from

    params: dict[str, Any] = {"per_page": PAGE_SIZE, "order": "desc"}
    if date_from is not None:
        params["date_from"] = date_from

    endpoint_config: Endpoint = {"path": path, "params": params, "data_selector_required": True}
    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": endpoint_config,
        "columns": {
            field["field"]: {
                "data_type": "date" if field["field"] == "started_at" else "timestamp",
            }
            for field in INCREMENTAL_FIELDS.get(endpoint, [])
        },
    }
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{API_BASE_URL}{api_version}/",
            "auth": {"type": "http_basic", "username": config.email, "password": config.api_key},
            "paginator": cast(PaginatorConfig, {"type": "page_number", "base_page": 1}),
            "request_timeout": 30,
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(DonorboxResumeConfig(page=int(state["page"]), date_from=date_from))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page} if resume is not None else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        column_hints=resource.column_hints,
        partition_keys=PRIMARY_KEYS,
        partition_mode="numerical",
        partition_size=PARTITION_SIZE,
        # The API does not identify its sort column. Save the watermark only after the complete scan.
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
