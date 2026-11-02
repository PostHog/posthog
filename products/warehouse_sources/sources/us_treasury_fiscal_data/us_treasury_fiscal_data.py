from datetime import date, datetime
from decimal import Decimal
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.settings import (
    ACCESS_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class FiscalDataResumeConfig:
    page: int
    lower_bound: str | None


def validate_credentials(schema_name: str | None = None) -> tuple[bool, str | None]:
    name = schema_name or "debt_to_penny"
    if name not in ENDPOINTS:
        return False, "Unknown US Treasury Fiscal Data table. Select a table from the source settings."
    with make_tracked_session() as session:
        response = session.get(BASE_URL + ENDPOINTS[name].path, params={"page[size]": 1}, timeout=30)
        try:
            response.raise_for_status()
        except HTTPError:
            if response.status_code in (401, 403):
                return False, ACCESS_ERROR
            raise
    return True, None


def fiscal_data_source(inputs: SourceInputs, manager: ResumableSourceManager[FiscalDataResumeConfig]) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError("Unknown US Treasury Fiscal Data table. Select a table from the source settings.")
    endpoint = ENDPOINTS[inputs.schema_name]
    if inputs.should_use_incremental_field and inputs.incremental_field != endpoint.incremental_field:
        raise ValueError(f"Select {endpoint.incremental_field} as the incremental field for this table.")

    lower_bound = None
    watermark = inputs.db_incremental_field_last_value
    if inputs.should_use_incremental_field and watermark is not None:
        if isinstance(watermark, datetime):
            lower_bound = watermark.date().isoformat()
        elif isinstance(watermark, date):
            lower_bound = watermark.isoformat()
        else:
            lower_bound = date.fromisoformat(str(watermark)[:10]).isoformat()

    initial_state = None
    if manager.can_resume():
        saved = manager.load_state()
        if saved is not None:
            initial_state = {"page": saved.page}
            lower_bound = saved.lower_bound

    sort_fields = list(dict.fromkeys((endpoint.incremental_field, *endpoint.primary_keys)))
    params: dict[str, Any] = {"page[size]": PAGE_SIZE, "sort": ",".join(sort_fields), "format": "json"}
    if lower_bound is not None:
        params["filter"] = f"{endpoint.incremental_field}:gte:{lower_bound}"

    endpoint_config: Endpoint = {
        "path": endpoint.path,
        "data_selector": "data",
        "data_selector_required": True,
        "params": params,
    }
    resource_config: EndpointResource = {
        "name": inputs.schema_name,
        "table_format": "delta",
        "endpoint": endpoint_config,
    }
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "paginator": PageNumberPaginator(base_page=1, page_param="page[number]", total_path="meta['total-pages']"),
            "request_timeout": (10.0, 60.0),
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(FiscalDataResumeConfig(page=int(state["page"]), lower_bound=lower_bound))

    def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        normalized = {key: None if value == "null" else value for key, value in row.items()}
        for field in endpoint.numeric_fields:
            if (value := normalized.get(field)) is not None:
                normalized[field] = Decimal(str(value))
        for field in ("record_date", "effective_date"):
            if (value := normalized.get(field)) is not None:
                normalized[field] = date.fromisoformat(str(value))
        if (value := normalized.get("src_line_nbr")) is not None:
            normalized["src_line_nbr"] = int(str(value))
        return normalized

    resource = rest_api_resource(
        config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    resource.add_map(normalize_row)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=["record_date"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
        on_complete=manager.clear_state,
    )
