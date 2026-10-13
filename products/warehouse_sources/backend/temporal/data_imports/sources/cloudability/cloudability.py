from datetime import date, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.settings import (
    ANOMALIES_LOOKBACK_DAYS,
    COST_REPORT_DIMENSIONS,
    COST_REPORT_LOOKBACK_DAYS,
    COST_REPORT_METRICS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


@frozen
class CloudabilityResumeConfig:
    cursor: str


def base_url(region: str) -> str:
    host = "api-eu.cloudability.com" if region == "eu" else "api.cloudability.com"
    return f"https://{host}/v3"


def get_resource(name: str, view_id: Optional[str]) -> EndpointResource:
    today = date.today()

    if name == "Costs":
        return {
            "name": "Costs",
            "table_name": "costs",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/reporting/cost/run",
                "data_selector": "results",
                "data_selector_required": True,
                "params": {
                    "start_date": (today - timedelta(days=COST_REPORT_LOOKBACK_DAYS)).isoformat(),
                    "end_date": today.isoformat(),
                    "dimensions": ",".join(COST_REPORT_DIMENSIONS),
                    "metrics": ",".join(COST_REPORT_METRICS),
                    "limit": 10000,
                },
                # Cloudability paginates cost reports >10,000 rows with a `pagination.next`
                # token rather than offset/limit once the first page is exhausted.
                "paginator": JSONResponseCursorPaginator(cursor_path="pagination.next", cursor_param="token"),
            },
            "table_format": "delta",
        }

    if name == "Views":
        return {
            "name": "Views",
            "table_name": "views",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/views",
                "data_selector_required": True,
                "paginator": "single_page",
            },
            "table_format": "delta",
        }

    if name == "BusinessMappingDimensions":
        return {
            "name": "BusinessMappingDimensions",
            "table_name": "business_mapping_dimensions",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/business-mappings/dimensions",
                "data_selector_required": True,
                "paginator": "single_page",
            },
            "table_format": "delta",
        }

    if name == "BusinessMappingMetrics":
        return {
            "name": "BusinessMappingMetrics",
            "table_name": "business_mapping_metrics",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/business-mappings/metrics/",
                "data_selector_required": True,
                "paginator": "single_page",
            },
            "table_format": "delta",
        }

    if name == "Anomalies":
        return {
            "name": "Anomalies",
            "table_name": "anomalies",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/anomalies",
                "data_selector_required": True,
                "params": {
                    "startDate": (today - timedelta(days=ANOMALIES_LOOKBACK_DAYS)).isoformat(),
                    "endDate": today.isoformat(),
                    "viewId": view_id,
                },
                "paginator": "single_page",
            },
            "table_format": "delta",
        }

    raise ValueError(f"Unknown Cloudability endpoint: {name}")


def validate_credentials(api_key: str, region: str) -> bool:
    res = make_tracked_session(redact_values=(api_key,)).get(
        f"{base_url(region)}/views",
        auth=(api_key, ""),
    )
    return res.status_code == 200


def cloudability_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudabilityResumeConfig],
    view_id: Optional[str],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(region),
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint, view_id)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only the Costs endpoint's cursor paginator ever returns resume state; the other
        # (single-page) endpoints call this with None and it's a no-op.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(CloudabilityResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
    )
