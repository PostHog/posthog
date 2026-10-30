from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.settings import (
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    MONITOR_HISTORY,
    MONITOR_HISTORY_DEFAULT_LOOKBACK,
    MONITOR_HISTORY_PRIMARY_KEYS,
    MONITOR_HISTORY_WINDOW,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.axiom import AxiomSourceConfig


@frozen
class AxiomResumeConfig:
    offset: int


def validate_credentials(config: AxiomSourceConfig, schema_name: str | None = None) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=config.api_token),
        headers={"x-axiom-org-id": config.org_id} if config.org_id else {},
        paginator=SinglePagePaginator(),
        max_retry_attempts=1,
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    if schema_name == MONITOR_HISTORY:
        # History needs a monitor ID, and the same `monitors|read` permission covers the list.
        schema_name = "monitors"
    endpoints = [schema_for_resource(ENDPOINTS, schema_name)] if schema_name else list(ENDPOINTS.values())
    for endpoint in endpoints:
        path = endpoint.get("path")
        if path is None:
            raise ValueError("Axiom endpoint path is required")
        params = dict(endpoint.get("params") or {})
        if endpoint["paginator"] != "single_page":
            params["limit"] = 1
        try:
            list(client.paginate(path, params=params, data_selector_required=True))
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 403 and schema_name is None:
                continue
            if status in AUTH_ERRORS:
                return False, AUTH_ERRORS[status]
            raise
        return True, None
    return False, AUTH_ERRORS[403]


def _client(config: AxiomSourceConfig) -> RESTClient:
    return RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=config.api_token),
        headers={"x-axiom-org-id": config.org_id} if config.org_id else {},
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _history_rows(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    # Windows share their bounds, so a row stays only in the window whose half-open range holds it.
    # All copies of a delivery share a timestamp and so land in the same window, which keeps the
    # delivery index stable between runs.
    seen: Counter[tuple[Any, Any, Any]] = Counter()
    kept = []
    for row in rows:
        timestamp = _parse_time(row.get("timestamp"))
        if timestamp is not None and not start <= timestamp < end:
            continue
        key = (row.get("checkId"), row.get("timestamp"), row.get("state"))
        kept.append({**row, "deliveryIndex": seen[key]})
        seen[key] += 1
    return kept


def axiom_monitor_history_source(
    config: AxiomSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AxiomResumeConfig],
) -> SourceResponse:
    last_value = _parse_time(inputs.db_incremental_field_last_value) if inputs.should_use_incremental_field else None

    def items() -> Iterator[list[dict[str, Any]]]:
        client = _client(config)
        end = datetime.now(UTC).replace(microsecond=0)
        monitors = [monitor for page in client.paginate("monitors", data_selector_required=True) for monitor in page]
        manager.safe_point()
        for monitor in monitors:
            start = _parse_time(monitor.get("createdAt")) or end - MONITOR_HISTORY_DEFAULT_LOOKBACK
            if last_value is not None:
                start = max(start, last_value)
            # Request bounds are whole seconds, so windows must be too or rows between a truncated
            # bound and the precise one would fall outside every window.
            start = start.replace(microsecond=0)
            while start < end:
                window_end = min(start + MONITOR_HISTORY_WINDOW, end)
                try:
                    pages = list(
                        client.paginate(
                            f"monitors/{monitor['id']}/history",
                            params={"startTime": _format_time(start), "endTime": _format_time(window_end)},
                            data_selector_required=True,
                        )
                    )
                except HTTPError as error:
                    # The monitor was deleted after the monitor list was read.
                    if error.response is not None and error.response.status_code == 404:
                        manager.safe_point()
                        break
                    raise
                rows = _history_rows([row for page in pages for row in page], start, window_end)
                if rows:
                    yield rows
                else:
                    manager.safe_point()
                start = window_end

    return SourceResponse(
        name=MONITOR_HISTORY,
        items=items,
        primary_keys=MONITOR_HISTORY_PRIMARY_KEYS,
        # Rows are ordered per monitor, not across monitors.
        sort_mode=None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["timestamp"],
        # No cursor is saved across monitors and windows, so a handoff would replay from the start.
        supports_resume=False,
    )


def axiom_source(
    config: AxiomSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AxiomResumeConfig],
) -> SourceResponse:
    if inputs.schema_name == MONITOR_HISTORY:
        return axiom_monitor_history_source(config, inputs, manager)
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    paginated = endpoint["paginator"] != "single_page"
    initial_state: dict[str, Any] | None = None
    if paginated and manager.can_resume():
        saved = manager.load_state()
        if saved is not None:
            initial_state = {"offset": saved.offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(AxiomResumeConfig(offset=int(state["offset"])))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.api_token},
            "headers": {"x-axiom-org-id": config.org_id} if config.org_id else {},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "primary_key": PRIMARY_KEYS,
                "write_disposition": "replace",
                "endpoint": {**endpoint, "data_selector": "", "data_selector_required": True},
            }
        ],
    }
    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint if paginated else None,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        on_complete=manager.clear_state if paginated else None,
        primary_keys=PRIMARY_KEYS,
        sort_mode=None,
        supports_resume=paginated,
    )
