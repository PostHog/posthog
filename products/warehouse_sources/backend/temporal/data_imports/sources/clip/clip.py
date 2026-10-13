import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.clip.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PERMISSION_ERROR,
    SETTLEMENT_HISTORY_DAYS,
    TRANSACTION_WINDOW,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    APIKeyAuth,
    HttpBasicAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clip import ClipSourceConfig


@frozen
class ClipResumeConfig:
    start: str
    end: str
    paginator_state: dict[str, Any] | None = None


def parse_start_date(value: str) -> datetime:
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter the start date in YYYY-MM-DD format.") from None
    if result.isoformat() != value:
        raise ValueError("Enter the start date in YYYY-MM-DD format.")
    if result > datetime.now(UTC).date():
        raise ValueError("The start date must be today or earlier.")
    return datetime.combine(result, time.min, UTC)


def validate_credentials(config: ClipSourceConfig) -> tuple[bool, str | None]:
    now = datetime.now(UTC)
    params: dict[str, str | int] = {
        "from": (now - timedelta(days=1)).isoformat(),
        "to": now.isoformat(),
        "limit": 1,
    }
    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}/payments",
            auth=HttpBasicAuth(config.api_key, config.secret_key),
            params=params,
            timeout=30,
        )
    if response.status_code == 401:
        return False, AUTH_ERROR
    if response.status_code == 403:
        return False, PERMISSION_ERROR
    response.raise_for_status()
    return True, None


def settlement_path(row: dict[str, Any]) -> dict[str, Any]:
    href = row["links"]["self"]["href"]
    prefix = "/settlements/"
    if not isinstance(href, str) or not href.startswith(prefix):
        raise ValueError("Clip returned an invalid deposit link. Contact Clip support.")
    try:
        identifier = UUID(href.removeprefix(prefix))
    except ValueError:
        raise ValueError("Clip returned an invalid deposit link. Contact Clip support.") from None
    return {**row, "settlement_path": f"settlements/{identifier}"}


def payment_parent(row: dict[str, Any]) -> dict[str, Any]:
    row["settlement_report_id"] = row.pop("_settlements_settlement_report_id")
    return row


def build_config(config: ClipSourceConfig, endpoint: str, start: datetime, end: datetime) -> RESTAPIConfig:
    if endpoint == "transactions":
        transaction_config: RESTAPIConfig = {
            "client": {
                "base_url": BASE_URL,
                "auth": HttpBasicAuth(config.api_key, config.secret_key),
                "allowed_hosts": [],
                "allow_redirects": False,
                "request_timeout": 30,
            },
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": "payments",
                        "params": {"from": start.isoformat(), "to": end.isoformat(), "limit": 100},
                        "data_selector": "items",
                        "data_selector_required": True,
                        "paginator": {
                            "type": "cursor",
                            "cursor_path": "meta.pagination_token",
                            "cursor_param": "pagination_token",
                            "raise_on_repeated_cursor": True,
                        },
                    },
                }
            ],
        }
        return transaction_config
    token = base64.b64encode(f"{config.api_key}:{config.secret_key}".encode()).decode()
    parent: EndpointResource = {
        "name": "settlements",
        "endpoint": {
            "path": "settlements",
            "params": {"from": start.date().isoformat(), "to": end.date().isoformat()},
            "data_selector": "settlements",
            "data_selector_required": True,
            "paginator": "single_page",
        },
    }
    resources: list[str | EndpointResource] = [parent]
    if endpoint == "settlement_payments":
        parent["data_map"] = settlement_path
        resources.append(
            {
                "name": endpoint,
                "include_from_parent": ["settlement_report_id"],
                "data_map": payment_parent,
                "endpoint": {
                    "path": "{settlement_path}",
                    "params": {
                        "settlement_path": {"type": "resolve", "resource": "settlements", "field": "settlement_path"},
                        "page_size": 100,
                    },
                    "data_selector": "settlement.details[*].payments[*]",
                    "paginator": {"type": "json_response", "next_url_path": "links.next.href"},
                },
            }
        )
    settlement_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": APIKeyAuth(api_key=f"Basic {token}", name="x-api-key"),
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": resources,
    }
    return settlement_config


def clip_source(
    config: ClipSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ClipResumeConfig],
) -> SourceResponse:
    primary_keys = schema_for_resource(ENDPOINTS, inputs.schema_name)
    floor = parse_start_date(config.start_date)
    now = datetime.now(UTC)
    if inputs.schema_name == "transactions" and inputs.should_use_incremental_field:
        watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
        if watermark is not None:
            floor = max(floor, watermark)
    elif inputs.schema_name != "transactions":
        floor = max(floor, datetime.combine(now.date() - timedelta(days=SETTLEMENT_HISTORY_DAYS), time.min, UTC))

    def items() -> Iterator[list[dict[str, Any]]]:
        end = now
        start = max(floor, end - TRANSACTION_WINDOW) if inputs.schema_name == "transactions" else floor
        initial_state = None
        if manager.can_resume():
            saved = manager.load_state()
            if saved is not None:
                start = datetime.fromisoformat(saved.start)
                end = datetime.fromisoformat(saved.end)
                initial_state = saved.paginator_state

        while end > floor:

            def checkpoint(
                state: dict[str, Any] | None, window_start: datetime = start, window_end: datetime = end
            ) -> None:
                manager.save_state(
                    ClipResumeConfig(start=window_start.isoformat(), end=window_end.isoformat(), paginator_state=state)
                )

            resources = rest_api_resources(
                build_config(config, inputs.schema_name, start, end),
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=checkpoint,
                initial_paginator_state=initial_state,
            )
            resource = next(resource for resource in resources if resource.name == inputs.schema_name)
            yield from resource
            if inputs.schema_name != "transactions" or start == floor:
                break
            end = start
            start = max(floor, end - TRANSACTION_WINDOW)
            initial_state = None
            manager.save_state(ClipResumeConfig(start=start.isoformat(), end=end.isoformat()))
            manager.safe_point()

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=primary_keys,
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
