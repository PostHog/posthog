from datetime import UTC, date, datetime
from typing import Any

from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.settings import (
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)

AUTH_ERROR = "EIA rejected the API key. Check your key. If EIA suspended it, wait before trying again."


@frozen
class EiaResumeConfig:
    offset: int
    start: str | None


def normalize_period(row: dict[str, Any]) -> dict[str, Any]:
    period = row["period"]
    if len(period) == 7:
        period += "-01"
    return {**row, "period": datetime.fromisoformat(period).replace(tzinfo=UTC)}


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        with make_tracked_session(redact_values=(api_key,)) as session:
            response = session.get(
                f"{BASE_URL}electricity/retail-sales/",
                auth=APIKeyAuth(api_key=api_key, name="api_key", location="query"),
                timeout=(10, 30),
            )
    except RequestException:
        return False, "Could not connect to EIA. Try again later."
    if response.status_code in (401, 403):
        return False, AUTH_ERROR
    if response.status_code != 200:
        return False, "Could not validate the EIA API key. Try again later."
    return True, None


def us_eia_source(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[EiaResumeConfig],
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    start = None
    if inputs.should_use_incremental_field:
        if inputs.incremental_field != "period":
            raise ValueError("EIA supports incremental sync only by period.")
        watermark = inputs.db_incremental_field_last_value
        if watermark is not None:
            date_format = "%Y-%m" if endpoint.frequency == "monthly" else "%Y-%m-%d"
            start = (
                watermark.strftime(date_format)
                if isinstance(watermark, date | datetime)
                else str(watermark)[: 7 if endpoint.frequency == "monthly" else 10]
            )

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None:
        # An offset belongs to its original date range, even when the pipeline advances its watermark.
        start = resume.start

    params: dict[str, Any] = {"frequency": endpoint.frequency, "data[]": list(endpoint.data_columns)}
    for index, column in enumerate(endpoint.primary_keys):
        params[f"sort[{index}][column]"] = column
        params[f"sort[{index}][direction]"] = "asc"
    if start is not None:
        params["start"] = start

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "request_timeout": (10, 60),
            "auth": {"type": "api_key", "name": "api_key", "api_key": api_key, "location": "query"},
            "paginator": {
                "type": "offset",
                "limit": PAGE_SIZE,
                "limit_param": "length",
                # EIA returns the total as a string. Stop on a short or empty page instead.
                "total_path": None,
            },
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "table_format": "delta",
                "endpoint": {
                    "path": endpoint.path,
                    "params": params,
                    "data_selector": "response.data",
                    "data_selector_required": True,
                },
                "data_map": normalize_period,
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is None:
            manager.clear_state()
        else:
            manager.save_state(EiaResumeConfig(offset=int(state["offset"]), start=start))

    resource = rest_api_resource(
        config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": resume.offset} if resume is not None else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=["period"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
    )
