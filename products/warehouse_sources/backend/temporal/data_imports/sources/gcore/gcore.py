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
    AGGREGATE_METRICS,
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    HISTORY_DAYS,
    INCREMENTAL_FILTER_PARAMS,
    LOGS_DELAY,
    LOGS_HISTORY_DAYS,
    LOGS_PAGE_SIZE,
    LOGS_WINDOW,
    PAGE_SIZE,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    STATISTICS_METRICS,
    WINDOWED_ENDPOINTS,
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
        resume_hook=save_checkpoint if inputs.schema_name not in WINDOWED_ENDPOINTS else None,
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


def _activity_log_metadata(row: dict[str, Any]) -> dict[str, Any]:
    # Request bodies and object states can contain origin credentials and signing keys.
    return {key: value for key, value in row.items() if key not in ("data", "actions")}


def _log_row(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "timestamp": datetime.fromtimestamp(row["timestamp"], UTC)}


def _aggregate_rows(body: dict[str, Any], day: datetime) -> list[dict[str, Any]]:
    if body and "resource" not in body:
        raise ValueError("Gcore aggregated statistics response does not contain resource groups.")
    rows = []
    for resource_id, group in body.get("resource", {}).items():
        for region, values in group.get("region", {}).items():
            metrics = values["metrics"]
            row: dict[str, Any] = {"resource_id": resource_id, "region": region, "date": day}
            for metric in AGGREGATE_METRICS:
                # A column name that starts with a digit needs quoting in every SQL query.
                column = "bandwidth_95_percentile" if metric == "95_percentile" else metric
                row[column] = metrics.get(metric)
            rows.append(row)
    return rows


def _logs(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GcoreCheckpoint],
    resume: GcoreCheckpoint | None,
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    end = (now - LOGS_DELAY).replace(minute=0, second=0, microsecond=0)
    start = (now - timedelta(days=LOGS_HISTORY_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        # Log timestamps have one-second precision, and appended rows are not deduplicated.
        start = max(start, _timestamp(inputs.db_incremental_field_last_value) + timedelta(seconds=1))
    offset = 0
    if resume is not None and resume.window_start is not None and resume.window_end is not None:
        start = _timestamp(resume.window_start)
        end = _timestamp(resume.window_end)
        offset = resume.offset
    while start < end:
        window_end = min(start + LOGS_WINDOW, end)
        resource = _resource(
            api_key,
            inputs,
            {
                "path": ENDPOINTS[inputs.schema_name],
                "params": {
                    "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ordering": "timestamp",
                },
                "data_selector": "data",
                "data_selector_required": True,
                "paginator": {"type": "offset", "limit": LOGS_PAGE_SIZE, "total_path": "meta.count"},
            },
            manager,
            GcoreCheckpoint(offset=offset),
        ).add_map(_log_row)
        pages = iter(resource)
        page = next(pages, None)
        if page is None:
            manager.save_state(GcoreCheckpoint(window_start=window_end.isoformat(), window_end=end.isoformat()))
        while page is not None:
            # Read one page ahead, so the checkpoint of the last page moves on to the next window.
            following = next(pages, None)
            offset += LOGS_PAGE_SIZE
            if following is None:
                checkpoint = GcoreCheckpoint(window_start=window_end.isoformat(), window_end=end.isoformat())
            else:
                checkpoint = GcoreCheckpoint(offset=offset, window_start=start.isoformat(), window_end=end.isoformat())
            manager.save_state(checkpoint)
            # The next window returns the rows at its start time.
            rows = [row for row in page if start <= row["timestamp"] < window_end]
            if rows:
                yield rows
            page = following
        offset = 0
        manager.safe_point()
        start = window_end


def _daily_statistics(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GcoreCheckpoint],
    resume: GcoreCheckpoint | None,
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    # Aggregated statistics leave out the last two hours, so only complete days are read.
    end = (now - timedelta(hours=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (now - timedelta(days=HISTORY_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        start = max(
            start, _timestamp(inputs.db_incremental_field_last_value).replace(hour=0, minute=0, second=0, microsecond=0)
        )
    if resume is not None and resume.window_start is not None and resume.window_end is not None:
        start = _timestamp(resume.window_start)
        end = _timestamp(resume.window_end)
    while start < end:
        day_end = start + timedelta(days=1)
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
                    # The upper bound is inclusive, so stop before the next day starts.
                    "to": (day_end - timedelta(seconds=1)).isoformat(),
                    "metrics": ",".join(AGGREGATE_METRICS),
                    "group_by": ["resource", "region"],
                },
            },
            manager,
        )
        rows = [row for page in resource for body in page for row in _aggregate_rows(body, start)]
        manager.save_state(GcoreCheckpoint(window_start=day_end.isoformat(), window_end=end.isoformat()))
        if rows:
            yield rows
        manager.safe_point()
        start = day_end


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
    if inputs.schema_name == "cdn_logs":
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: _logs(api_key, inputs, manager, resume),
            primary_keys=PRIMARY_KEYS[inputs.schema_name],
            partition_keys=PARTITION_KEYS[inputs.schema_name],
            partition_mode="datetime",
            partition_format="day",
            sort_mode="asc",
        )
    if inputs.schema_name == "cdn_daily_statistics":
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: _daily_statistics(api_key, inputs, manager, resume),
            primary_keys=PRIMARY_KEYS[inputs.schema_name],
            partition_keys=PARTITION_KEYS[inputs.schema_name],
            partition_mode="datetime",
            partition_format="month",
            sort_mode="desc",
        )
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
    filter_param = INCREMENTAL_FILTER_PARAMS.get(inputs.schema_name)
    if filter_param is not None and inputs.should_use_incremental_field:
        if inputs.db_incremental_field_last_value is not None:
            params[filter_param] = _timestamp(inputs.db_incremental_field_last_value).isoformat()
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
    elif inputs.schema_name == "activity_logs":
        resource.add_map(_activity_log_metadata)
    return SourceResponse(
        name=inputs.schema_name, items=lambda: resource, primary_keys=PRIMARY_KEYS[inputs.schema_name], sort_mode="desc"
    )
