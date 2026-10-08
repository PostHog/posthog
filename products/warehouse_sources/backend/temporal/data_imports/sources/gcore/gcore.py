from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.settings import (
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    HISTORY_DAYS,
    PAGE_SIZE,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    STATISTICS_METRICS,
)


@frozen
class GcoreCheckpoint:
    offset: int = 0
    window_start: str | None = None
    window_end: str | None = None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    with make_tracked_session() as session:
        response = session.get(
            BASE_URL + "resources",
            params={"limit": 1},
            auth=APIKeyAuth(api_key=f"APIKey {api_key}"),
            timeout=(10, 30),
        )
        if response.status_code in AUTH_ERRORS:
            return False, AUTH_ERRORS[response.status_code]
        response.raise_for_status()
    return True, None


def _timestamp(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _resource(
    api_key: str,
    inputs: SourceInputs,
    endpoint: Endpoint,
    manager: ResumableSourceManager[GcoreCheckpoint],
    resume: GcoreCheckpoint | None = None,
) -> Resource:
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "Authorization", "api_key": f"APIKey {api_key}"},
            "allow_redirects": False,
            "allowed_hosts": [],
            "request_timeout": (10, 60),
        },
        "resources": [{"name": inputs.schema_name, "endpoint": endpoint}],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(GcoreCheckpoint(offset=int(state["offset"])))

    return rest_api_resource(
        config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint if inputs.schema_name not in STATISTICS_METRICS else None,
        initial_paginator_state={"offset": resume.offset} if resume is not None else None,
    )


def _statistics_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    if body and "resource" not in body:
        raise ValueError("Gcore statistics response does not contain resource groups.")
    rows = []
    for resource_id, group in body.get("resource", {}).items():
        for metric, points in group["metrics"].items():
            for timestamp, value in points:
                rows.append(
                    {
                        "resource_id": resource_id,
                        "timestamp": datetime.fromtimestamp(timestamp, UTC),
                        "metric": metric,
                        "value": value,
                    }
                )
    return rows


def _resource_metadata(row: dict[str, Any]) -> dict[str, Any]:
    # Resource options and rules can contain signing keys and origin request headers.
    safe_fields = {"id", "cname", "created", "updated", "originGroup", "status"}
    return {key: value for key, value in row.items() if key in safe_fields}


def _origin_metadata(row: dict[str, Any]) -> dict[str, Any]:
    # Origin authentication settings can contain storage credentials.
    result = {key: value for key, value in row.items() if key != "auth"}
    if "sources" in result:
        result["sources"] = [
            {key: value for key, value in source.items() if key != "config"} for source in result["sources"]
        ]
    return result


def _statistics(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GcoreCheckpoint],
    resume: GcoreCheckpoint | None,
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = (now - timedelta(days=HISTORY_DAYS)).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        start = max(
            start, _timestamp(inputs.db_incremental_field_last_value).replace(minute=0, second=0, microsecond=0)
        )
    if resume is not None and resume.window_start is not None and resume.window_end is not None:
        start = _timestamp(resume.window_start)
        end = _timestamp(resume.window_end)
    while start < end:
        window_end = min(start + timedelta(days=1), end)
        resource = _resource(
            api_key,
            inputs,
            {
                "path": ENDPOINTS[inputs.schema_name],
                "paginator": "single_page",
                "data_selector": "$",
                "params": {
                    "service": "CDN",
                    "from": start.isoformat(),
                    "to": window_end.isoformat(),
                    "granularity": "1h",
                    "group_by": "resource",
                    "metrics": STATISTICS_METRICS[inputs.schema_name],
                },
            },
            manager,
        ).add_map(_statistics_rows)
        for page in resource:
            # Exclude the next bucket when the API treats the upper bound as inclusive.
            rows = [row for row in page if start <= row["timestamp"] < window_end]
            manager.save_state(GcoreCheckpoint(window_start=window_end.isoformat(), window_end=end.isoformat()))
            if rows:
                yield rows
        manager.save_state(GcoreCheckpoint(window_start=window_end.isoformat(), window_end=end.isoformat()))
        manager.safe_point()
        start = window_end


def gcore_source(
    api_key: str, inputs: SourceInputs, manager: ResumableSourceManager[GcoreCheckpoint]
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unknown Gcore table: {inputs.schema_name}")
    resume = manager.load_state() if manager.can_resume() else None
    if inputs.schema_name in STATISTICS_METRICS:
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: _statistics(api_key, inputs, manager, resume),
            primary_keys=PRIMARY_KEYS[inputs.schema_name],
            partition_keys=PARTITION_KEYS[inputs.schema_name],
            partition_mode="datetime",
            partition_format="month",
            sort_mode="desc",
        )
    params: dict[str, Any] = {}
    if inputs.schema_name == "resources" and inputs.should_use_incremental_field:
        if inputs.db_incremental_field_last_value is not None:
            params["min_updated"] = _timestamp(inputs.db_incremental_field_last_value).isoformat()
    resource = _resource(
        api_key,
        inputs,
        {
            "path": ENDPOINTS[inputs.schema_name],
            "params": params,
            "data_selector": "results",
            "data_selector_required": True,
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": "count"},
        },
        manager,
        resume,
    )
    if inputs.schema_name == "resources":
        resource.add_map(_resource_metadata)
    elif inputs.schema_name == "origin_groups":
        resource.add_map(_origin_metadata)
    return SourceResponse(
        name=inputs.schema_name, items=lambda: resource, primary_keys=PRIMARY_KEYS[inputs.schema_name], sort_mode="desc"
    )
