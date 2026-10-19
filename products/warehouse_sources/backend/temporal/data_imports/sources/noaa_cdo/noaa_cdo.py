from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.noaacdo import (
    NoaaCdoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.settings import (
    API_BASE_URL,
    AUTH_ERROR,
    ENDPOINTS,
    PAGE_SIZE,
    REQUEST_ERROR,
    RESPONSE_ACTIONS,
)


@frozen
class NoaaCdoResumeConfig:
    offset: int = 1
    window_start: str | None = None
    end_date: str | None = None
    complete: bool = False


def validate_config(config: NoaaCdoSourceConfig) -> date:
    try:
        start = date.fromisoformat(config.start_date)
    except ValueError:
        raise ValueError("Enter the start date as YYYY-MM-DD.") from None
    if start.isoformat() != config.start_date:
        raise ValueError("Enter the start date as YYYY-MM-DD.")
    if start > datetime.now(UTC).date():
        raise ValueError("The start date must be today or earlier.")
    if not config.dataset_id.strip() or not config.station_id.strip():
        raise ValueError("Enter one dataset ID and one station ID.")
    return start


def rest_config(
    config: NoaaCdoSourceConfig, endpoint: str, params: dict[str, Any], api_version: str, *, probe: bool = False
) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": f"{API_BASE_URL}/{api_version}/",
            "auth": {"type": "api_key", "name": "token", "location": "header", "api_key": config.api_token},
            "paginator": "single_page"
            if probe
            else {
                "type": "offset",
                "limit": PAGE_SIZE,
                "offset": 1,
                # NOAA offsets are one-based; the shared total check assumes zero-based offsets.
                "total_path": None,
            },
            "request_timeout": (10, 60),
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint,
                    "params": params,
                    "data_selector": "results",
                    "data_selector_required": True,
                    "data_selector_empty_ok": True,
                    "response_actions": RESPONSE_ACTIONS,
                },
            }
        ],
    }


def validate_credentials(config: NoaaCdoSourceConfig, team_id: int, api_version: str) -> tuple[bool, str | None]:
    try:
        validate_config(config)
    except ValueError as error:
        return False, str(error)
    try:
        resource = rest_api_resource(
            rest_config(config, "datasets", {"limit": 1}, api_version, probe=True), team_id, "", None
        )
        list(resource)
    except ValueError as error:
        if str(error) in {AUTH_ERROR, REQUEST_ERROR}:
            return False, str(error)
        raise
    return True, None


def noaa_cdo_source(
    config: NoaaCdoSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[NoaaCdoResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    last_value: str | date | datetime | None = None,
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError("Unknown NOAA table. Select a table from the source configuration.")
    start = validate_config(config)
    if endpoint == "data" and should_use_incremental_field and last_value is not None:
        watermark = datetime.fromisoformat(last_value) if isinstance(last_value, str) else last_value
        watermark_date = watermark.date() if isinstance(watermark, datetime) else watermark
        # Recent observations can arrive late or change after their first publication.
        start = max(start, watermark_date - timedelta(days=7))

    def items() -> Iterator[list[dict[str, Any]]]:
        resume = manager.load_state() if manager.can_resume() else None
        state = resume or NoaaCdoResumeConfig(
            window_start=start.isoformat(), end_date=datetime.now(UTC).date().isoformat()
        )
        while not state.complete:
            params: dict[str, Any] = {}
            if endpoint != "datasets":
                params["datasetid"] = config.dataset_id.strip()
            if endpoint in {"data", "datasets", "datatypes", "datacategories"}:
                params["stationid"] = config.station_id.strip()

            next_window: str | None = None
            final_window = True
            if endpoint == "data":
                window_start = date.fromisoformat(state.window_start or start.isoformat())
                end_date = date.fromisoformat(state.end_date or datetime.now(UTC).date().isoformat())
                if window_start > end_date:
                    return
                window_end = min(window_start + timedelta(days=364), end_date)
                params.update(startdate=window_start.isoformat(), enddate=window_end.isoformat(), units="metric")
                next_window = (window_end + timedelta(days=1)).isoformat()
                final_window = window_end == end_date
            else:
                params.update(sortfield="id", sortorder="asc")

            def save_checkpoint(
                paginator_state: dict[str, Any] | None,
                next_window: str | None = next_window,
                final_window: bool = final_window,
            ) -> None:
                nonlocal state
                state = NoaaCdoResumeConfig(
                    offset=int(paginator_state["offset"]) if paginator_state else 1,
                    window_start=state.window_start if paginator_state else next_window,
                    end_date=state.end_date,
                    complete=paginator_state is None and final_window,
                )
                manager.save_state(state)
                manager.safe_point()

            yield from rest_api_resource(
                rest_config(config, endpoint, params, api_version),
                team_id,
                job_id,
                None,
                resume_hook=save_checkpoint,
                initial_paginator_state={"offset": state.offset},
            )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["station", "datatype", "date"] if endpoint == "data" else ["id"],
        # NOAA does not document chronological ordering for observations.
        sort_mode="desc",
        partition_keys=["date"] if endpoint == "data" else None,
        partition_mode="datetime" if endpoint == "data" else None,
        partition_format="month" if endpoint == "data" else None,
    )
