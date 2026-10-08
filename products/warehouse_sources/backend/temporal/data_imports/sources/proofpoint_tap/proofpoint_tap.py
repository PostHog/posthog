from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.proofpointtap import (
    ProofpointTapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.settings import (
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    MIN_WINDOW,
    OVERLAP,
    RETENTION,
    WINDOW,
)


@frozen
class TapCursor:
    cursor_kind: ClassVar[str] = "proofpoint_tap_query_end"
    query_end_time: str


@frozen
class TapResumeState:
    next_start: str
    end: str


def parse_timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def get_resource(
    config: ProofpointTapSourceConfig,
    endpoint: str,
    params: dict[str, Any],
    team_id: int,
    job_id: str,
    api_version: str,
) -> Resource:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/siem/",
            "auth": {"type": "http_basic", "username": config.service_principal, "password": config.secret},
            "paginator": "single_page",
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": settings.path,
                    "params": {"format": "json", **params},
                    "data_selector": "$",
                    "data_selector_required": True,
                },
            }
        ],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def validate_credentials(
    config: ProofpointTapSourceConfig, team_id: int, schema_name: str | None, api_version: str
) -> tuple[bool, str | None]:
    try:
        list(get_resource(config, schema_name or "clicks_blocked", {"sinceSeconds": 30}, team_id, "", api_version))
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 403 and schema_name is None:
            return True, None
        if status is not None and status in AUTH_ERRORS:
            return False, AUTH_ERRORS[status]
        raise
    return True, None


def proofpoint_tap_source(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[TapResumeState],
    cursor_manager: SourceCursorManager[TapCursor],
    api_version: str,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)

    def items() -> Iterator[list[dict[str, Any]]]:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        # Leave time for the first request before the oldest interval expires.
        earliest = now - RETENTION + 2 * OVERLAP
        end = now - OVERLAP
        start = earliest
        cursor = cursor_manager.load() if inputs.should_use_incremental_field else None
        if cursor is not None:
            start = max(earliest, parse_timestamp(cursor.query_end_time) - OVERLAP)
        elif inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            start = max(earliest, parse_timestamp(inputs.db_incremental_field_last_value) - OVERLAP)

        resume = manager.load_state() if manager.can_resume() else None
        if resume is not None:
            start = max(earliest, parse_timestamp(resume.next_start))
            end = min(end, parse_timestamp(resume.end))

        last_end: datetime | None = None
        while end - start >= MIN_WINDOW:
            window_end = min(start + WINDOW, end)
            resource = get_resource(
                config,
                inputs.schema_name,
                {"interval": f"{start.isoformat()}/{window_end.isoformat()}"},
                inputs.team_id,
                inputs.job_id,
                api_version,
            )
            payloads = [payload for page in resource for payload in page]
            if len(payloads) != 1 or not isinstance(payloads[0], dict):
                raise ValueError("Proofpoint TAP returned an invalid response. Retry the sync.")
            payload = payloads[0]
            raw_end = payload.get("queryEndTime")
            rows = payload.get(settings.selector)
            if (
                not isinstance(raw_end, str)
                or not isinstance(rows, list)
                or any(not isinstance(row, dict) for row in rows)
            ):
                raise ValueError("Proofpoint TAP returned an invalid response. Retry the sync.")
            query_end = parse_timestamp(raw_end)
            if query_end != window_end:
                raise ValueError("Proofpoint TAP returned an invalid query end time. Retry the sync.")
            if any(not row.get(settings.primary_key) for row in rows):
                raise ValueError("Proofpoint TAP returned an event without its unique ID. Retry the sync.")

            # Event timestamps can predate detection, so only the queried interval can advance the cursor.
            for row in rows:
                row["query_end_time"] = query_end
            manager.save_state(TapResumeState(next_start=query_end.isoformat(), end=end.isoformat()))
            if rows:
                yield rows
            manager.safe_point()
            last_end = query_end
            start = query_end

        if last_end is not None:
            cursor_manager.stage(TapCursor(query_end_time=last_end.isoformat()))
        elif resume is not None and start >= end:
            cursor_manager.stage(TapCursor(query_end_time=end.isoformat()))

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=[settings.primary_key],
        partition_keys=[settings.event_time],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
