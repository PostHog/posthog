import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.settings import (
    PAGE_SIZE,
    UPDATED_DATE_FIELD,
    XERO_API_BASE_URL,
    XERO_CONNECTIONS_URL,
    XERO_ENDPOINTS,
)

# Xero sends `/Date(1539993600000+0000)/`: UTC epoch milliseconds, then the organisation's zone offset.
_MS_JSON_DATE = re.compile(r"^/Date\((-?\d+)([+-]\d{4})?\)/$")

REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class XeroResumeConfig:
    page: int


def convert_ms_json_dates(row: dict[str, Any]) -> dict[str, Any]:
    """Turn top-level `/Date(...)/` strings into UTC datetimes so `UpdatedDateUTC` can be a cursor."""
    converted: dict[str, Any] = {}
    for key, value in row.items():
        match = _MS_JSON_DATE.match(value) if isinstance(value, str) else None
        converted[key] = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC) if match else value
    return converted


def _if_modified_since(last_value: Any) -> str | None:
    parsed = parse_datetime_value(last_value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def xero_source(
    auth: AuthConfigBase,
    tenant_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[XeroResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    config = XERO_ENDPOINTS[endpoint]
    incremental = should_use_incremental_field and config.incremental

    headers = {"Accept": "application/json", "xero-tenant-id": tenant_id}
    modified_since = _if_modified_since(db_incremental_field_last_value) if incremental else None
    if modified_since is not None:
        headers["If-Modified-Since"] = modified_since

    params: dict[str, Any] = dict(config.extra_params)
    if config.incremental:
        # Ascending order keeps the pipeline's watermark checkpoint valid after each page.
        params["order"] = f"{UPDATED_DATE_FIELD} ASC"
    paginator: BasePaginator
    if config.paginated:
        params["pageSize"] = PAGE_SIZE
        paginator = PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.pageCount")
    else:
        paginator = SinglePagePaginator()

    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "table_format": "delta",
        "data_map": convert_ms_json_dates,
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_key,
            "paginator": paginator,
        },
    }
    rest_config: RESTAPIConfig = {
        "client": {"base_url": XERO_API_BASE_URL, "headers": headers, "auth": auth},
        "resource_defaults": {},
        "resources": [resource],
    }

    # A page number is only valid under one If-Modified-Since value, so incremental runs resume from the watermark.
    resumable = config.paginated and not incremental
    initial_paginator_state: dict[str, Any] | None = None
    if resumable and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if resumable and state is not None and state.get("page") is not None:
            resumable_source_manager.save_state(XeroResumeConfig(page=int(state["page"])))

    rest_resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: rest_resource,
        primary_keys=[config.primary_key],
        sort_mode="asc",
        column_hints=rest_resource.column_hints,
    )


def list_organisations(access_token: str) -> list[dict[str, Any]]:
    """The Xero organisations the token can read, from the connections endpoint."""
    session = make_tracked_session(redact_values=(access_token,), allow_redirects=False)
    response = session.get(
        XERO_CONNECTIONS_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    # A connection can also be a Xero Practice Manager tenant, which has no Accounting API.
    return [connection for connection in response.json() if connection.get("tenantType") == "ORGANISATION"]


def probe_organisation(access_token: str, tenant_id: str) -> int:
    session = make_tracked_session(redact_values=(access_token,), allow_redirects=False)
    response = session.get(
        f"{XERO_API_BASE_URL}/Organisation",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "xero-tenant-id": tenant_id},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return response.status_code
