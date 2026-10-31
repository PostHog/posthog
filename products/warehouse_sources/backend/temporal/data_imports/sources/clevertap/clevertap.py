from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.settings import (
    ENDPOINTS,
    EXCLUDED_EVENTS,
    PAGE_SIZE,
    REGIONS,
    RESPONSE_ACTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clevertap import (
    ClevertapSourceConfig,
)


@frozen
class ClevertapResumeConfig:
    cursor: str | None
    completed: bool = False


class ClevertapPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._cursor: str | None = None

    def init_request(self, request: Request) -> None:
        if self._cursor is not None:
            self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "success":
            raise ValueError("CleverTap returned an unexpected export response.")
        if response.request.method == "POST":
            cursor = body.get("cursor")
            if not isinstance(cursor, str) or not cursor:
                raise ValueError("CleverTap did not return an export cursor.")
        else:
            records = body.get("records", [])
            if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
                raise ValueError("CleverTap returned an invalid records list.")
            cursor = body.get("next_cursor")
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise ValueError("CleverTap returned an invalid export cursor.")
        self._cursor = cursor
        self._has_next_page = cursor is not None

    def update_request(self, request: Request) -> None:
        request.method = "GET"
        request.json = None
        request.data = None
        request.params = {"cursor": self._cursor}

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"cursor": self._cursor} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._cursor = state["cursor"]


def validate_configuration(config: ClevertapSourceConfig) -> date:
    if config.region not in REGIONS:
        raise ValueError("Select a supported CleverTap region.")
    if not config.event_name.strip():
        raise ValueError("Enter a CleverTap event name.")
    for credential in (config.account_id, config.passcode):
        if not credential or not credential.isascii() or any(character in credential for character in "\r\n"):
            raise ValueError("Enter a valid CleverTap account ID and passcode.")
    try:
        start = datetime.strptime(config.start_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Enter the start date in YYYY-MM-DD format.") from None
    if start > datetime.now(UTC).date() - timedelta(days=1):
        raise ValueError("The start date must be before today (UTC).")
    return start


def build_rest_config(config: ClevertapSourceConfig, endpoint: str, *, probe: bool = False) -> RESTAPIConfig:
    definition = schema_for_resource(ENDPOINTS, endpoint)
    start = validate_configuration(config)
    if endpoint == "events" and config.event_name in EXCLUDED_EVENTS:
        raise ValueError("CleverTap does not export this notification event. Select another event name.")
    end = datetime.now(UTC).date() - timedelta(days=1)
    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": {
            "path": definition.path,
            "method": "POST",
            "params": {"batch_size": 1 if probe else PAGE_SIZE, "app": "true", "events": "true", "profile": "true"},
            "json": {
                "event_name": config.event_name,
                "from": int((end if probe else start).strftime("%Y%m%d")),
                "to": int(end.strftime("%Y%m%d")),
            },
            "data_selector": "$" if probe else "records",
            "paginator": SinglePagePaginator() if probe else ClevertapPaginator(),
            "response_actions": RESPONSE_ACTIONS,
        },
    }
    return {
        "client": {
            "base_url": REGIONS[config.region],
            "headers": {"X-CleverTap-Account-Id": config.account_id},
            "auth": {
                "type": "api_key",
                "name": "X-CleverTap-Passcode",
                "api_key": config.passcode,
                "location": "header",
            },
            "session": make_tracked_session(redact_values=(config.account_id, config.passcode)),
            "request_timeout": (10, 60),
            "retry_budget_seconds": 200,
            "retry_after_max_seconds": 60,
            "allow_redirects": False,
        },
        "resources": [resource],
    }


def probe_credentials(config: ClevertapSourceConfig, team_id: int, endpoint: str) -> None:
    resource = rest_api_resource(
        build_rest_config(config, endpoint, probe=True), team_id, "clevertap-credentials", None
    )
    for page in resource:
        if len(page) != 1 or page[0].get("status") != "success" or not page[0].get("cursor"):
            raise ValueError("CleverTap did not return an export cursor.")


def clevertap_source(
    config: ClevertapSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClevertapResumeConfig],
) -> SourceResponse:
    definition = schema_for_resource(ENDPOINTS, endpoint)
    rest_config = build_rest_config(config, endpoint)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.completed:
        return SourceResponse(
            name=endpoint, items=lambda: iter(()), primary_keys=list(definition.primary_keys), sort_mode=None
        )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        resumable_source_manager.save_state(
            ClevertapResumeConfig(cursor=state["cursor"] if state else None, completed=state is None)
        )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume is not None else None,
    )
    if endpoint == "events":

        def add_event_fields(row: dict[str, Any]) -> dict[str, Any]:
            row["event_name"] = config.event_name
            # CleverTap ts uses account time, so the partition date must not imply UTC.
            row["event_date"] = datetime.strptime(str(row["ts"]), "%Y%m%d%H%M%S").date().isoformat()
            return row

        resource.add_map(add_event_fields)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(definition.primary_keys),
        partition_keys=[definition.partition_key] if definition.partition_key else None,
        partition_mode="datetime" if definition.partition_key else None,
        partition_format="month" if definition.partition_key else None,
        sort_mode=None,
    )
