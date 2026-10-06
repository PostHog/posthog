from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mono import MonoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mono.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)


@frozen
class MonoResumeConfig:
    paginator_state: dict[str, Any]
    start: str | None = None
    end: str | None = None


class MonoPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        next_url = response.json()["meta"]["next"]
        if not next_url:
            self._has_next_page = False
            return

        # Mono's documented next links omit date filters and can omit the accounts path segment.
        # Use only their page number to preserve the endpoint and filters.
        values = parse_qs(urlsplit(next_url).query).get("page", [])
        if len(values) != 1 or not values[0].isdigit() or int(values[0]) <= self.page:
            raise ValueError("Mono returned an invalid pagination link.")
        self.page = int(values[0])
        self._has_next_page = True


def parse_start_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter the transaction start date in YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ValueError("Enter the transaction start date in YYYY-MM-DD format.")
    if parsed >= datetime.now(UTC).date():
        raise ValueError("Enter a transaction start date before today.")
    return parsed


def client_config(api_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{BASE_URL}/{api_version}/",
        "auth": {"type": "api_key", "name": "mono-sec-key", "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 60),
        "paginator": MonoPaginator(),
        "allowed_hosts": ["api.withmono.com"],
        "allow_redirects": False,
    }


def validate_credentials(config: MonoSourceConfig, api_version: str, team_id: int) -> tuple[bool, str | None]:
    try:
        parse_start_date(config.start_date)
    except ValueError as error:
        return False, str(error)

    rest_config: RESTAPIConfig = {
        "client": client_config(config.api_key, api_version),
        "resources": [
            {
                "name": "customers",
                "endpoint": {
                    "path": "customers",
                    "paginator": "single_page",
                    "data_selector": "data",
                    "data_selector_required": True,
                },
            }
        ],
    }
    try:
        list(rest_api_resource(rest_config, team_id, "", None))
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return False, AUTH_ERROR if error.response.status_code == 401 else PERMISSION_ERROR
        raise
    return True, None


def mono_source(
    config: MonoSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[MonoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    params: dict[str, Any] = {}
    start = end = None
    if endpoint == "transactions":
        start_day = parse_start_date(config.start_date)
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            watermark = parse_datetime_value(db_incremental_field_last_value)
            if watermark is None:
                raise ValueError(
                    "Mono received an invalid transaction watermark. Reset the transaction table and retry."
                )
            # A one-day overlap covers the API's date precision and avoids equal start/end dates.
            start_day = max(start_day, watermark.date() - timedelta(days=1))
        start = resume.start if resume else start_day.strftime("%d-%m-%Y")
        end = resume.end if resume else datetime.now(UTC).strftime("%d-%m-%Y")
        params = {
            "account_id": {"type": "resolve", "resource": "accounts", "field": "id"},
            "start": start,
            "end": end,
            "paginate": "true",
            "limit": 100,
        }

    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "table_format": "delta",
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if endpoint == "transactions" and should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": path,
            "params": params,
            "data_selector": "data",
            "data_selector_required": True,
        },
    }
    resources: list[str | EndpointResource] = []
    if endpoint == "transactions":
        resource["include_from_parent"] = ["id"]
        resources.append(
            {
                "name": "accounts",
                "endpoint": {"path": "accounts", "data_selector": "data", "data_selector_required": True},
            }
        )
    resources.append(resource)

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(MonoResumeConfig(paginator_state=state, start=start, end=end))

    rest_config: RESTAPIConfig = {"client": client_config(config.api_key, api_version), "resources": resources}
    built = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    result = next(item for item in built if item.name == endpoint)
    if endpoint == "transactions":
        result.add_map(rename_parent_fields("accounts", {"id": "account_id"}))
    return SourceResponse(
        name=endpoint,
        items=lambda: result,
        primary_keys=PRIMARY_KEYS[endpoint],
        # Each account has its own transaction order, so only checkpoint the watermark after all accounts finish.
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
