import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.settings import (
    ENDPOINT_PATHS,
    INCREMENTAL_FIELDS,
    V2_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BASE_URL = "https://api.bigcommerce.com"
# BigCommerce caps `limit` at 250 on both the V3 catalog/customers collections and the
# legacy V2 orders collection.
PAGE_SIZE = 250


@dataclasses.dataclass
class BigCommerceResumeConfig:
    page: int


def _to_v3_timestamp(value: Any) -> str:
    """Format an incremental cursor value for the V3 `date_modified:min` filter, which
    expects ISO 8601 (e.g. `2019-08-24T14:15:22Z`)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _to_v2_timestamp(value: Any) -> str:
    """Format an incremental cursor value for the legacy V2 `min_date_modified` filter,
    which — unlike V3 — expects an RFC 2822 / HTTP-date string (e.g. `Sun, 22 Aug
    2021 00:00:00 +0000`)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return str(value)


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    path = ENDPOINT_PATHS[name]
    is_v2 = name in V2_ENDPOINTS
    use_incremental = should_use_incremental_field and name in INCREMENTAL_FIELDS

    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if use_incremental:
        if is_v2:
            params["min_date_modified"] = {
                "type": "incremental",
                "cursor_path": "date_modified",
                "initial_value": None,
                "convert": _to_v2_timestamp,
            }
        else:
            params["date_modified:min"] = {
                "type": "incremental",
                "cursor_path": "date_modified",
                "initial_value": None,
                "convert": _to_v3_timestamp,
            }

    # V3 reports the page count directly, so pagination stops without an extra empty-page
    # request. V2 has no such envelope, so it falls back to stopping on a short/empty page.
    paginator = PageNumberPaginator(
        base_page=1,
        page_param="page",
        total_path=None if is_v2 else "meta.pagination.total_pages",
    )

    endpoint: Endpoint = {
        "path": path,
        "params": params,
        "paginator": paginator,
        # V3 wraps rows in {"data": [...], "meta": {...}}; the legacy V2 orders endpoint
        # returns a bare JSON array.
        "data_selector": None if is_v2 else "data",
    }

    return {
        "name": name,
        "table_name": name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def bigcommerce_source(
    store_hash: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BigCommerceResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/stores/{store_hash}",
            "auth": {
                "type": "api_key",
                "name": "X-Auth-Token",
                "api_key": access_token,
                "location": "header",
            },
            "headers": {"Accept": "application/json"},
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup
        # on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(BigCommerceResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(store_hash: str, access_token: str) -> Optional[int]:
    """Probe a cheap V3 endpoint. Returns the HTTP status code, or None on a connection error."""
    try:
        response = make_tracked_session(redact_values=(access_token,)).get(
            f"{BASE_URL}/stores/{store_hash}/v3/catalog/products",
            params={"limit": 1},
            headers={"X-Auth-Token": access_token, "Accept": "application/json"},
            timeout=30,
        )
    except Exception:
        return None
    return response.status_code
