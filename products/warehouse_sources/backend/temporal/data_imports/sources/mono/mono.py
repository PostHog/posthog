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
    Endpoint,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mono import MonoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mono.settings import (
    AUTH_ERROR,
    BASE_URL,
    DATE_FILTERS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGE_SIZE,
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


def incremental_start(
    endpoint: str, should_use_incremental_field: bool, db_incremental_field_last_value: object
) -> date | None:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is None:
        raise ValueError(f"Mono received an invalid {endpoint} watermark. Reset the {endpoint} table and retry.")
    # A one-day overlap covers the API's date precision and avoids equal start/end dates.
    return watermark.date() - timedelta(days=1)


def endpoint_paginator(endpoint: str) -> PaginatorConfig | None:
    if endpoint in ("institutions", "mandate_debits"):
        return "single_page"
    if endpoint == "payments":
        return PageNumberPaginator(base_page=1, total_path="meta.paging.pages")
    if endpoint == "mandates":
        # The documented response has no paging metadata, so stop at the first empty page.
        return PageNumberPaginator(base_page=1)
    return None


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
    start_day = incremental_start(endpoint, should_use_incremental_field, db_incremental_field_last_value)
    if endpoint == "transactions":
        configured_start = parse_start_date(config.start_date)
        start_day = max(configured_start, start_day) if start_day else configured_start
    if resume is not None:
        start, end = resume.start, resume.end
    elif endpoint in DATE_FILTERS and start_day is not None:
        date_format = DATE_FILTERS[endpoint][2]
        start, end = start_day.strftime(date_format), datetime.now(UTC).strftime(date_format)
    if start is not None and end is not None and endpoint in DATE_FILTERS:
        start_param, end_param, _ = DATE_FILTERS[endpoint]
        params = {start_param: start, end_param: end}
    if endpoint == "transactions":
        params = {
            "account_id": {"type": "resolve", "resource": "accounts", "field": "id"},
            **params,
            "paginate": "true",
            "limit": PAGE_SIZE,
        }
    elif endpoint in ("payments", "mandates"):
        params["limit"] = PAGE_SIZE

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "data.payments" if endpoint == "payments" else "data",
        "data_selector_required": True,
    }
    paginator = endpoint_paginator(endpoint)
    if paginator is not None:
        endpoint_config["paginator"] = paginator

    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "table_format": "delta",
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if endpoint in INCREMENTAL_FIELDS and should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
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
        # Mono lists newest first, and transactions restart that order for each account,
        # so only checkpoint the watermark after the whole sync finishes.
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
