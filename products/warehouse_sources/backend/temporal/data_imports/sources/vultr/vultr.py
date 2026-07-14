from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.settings import ENDPOINTS

VULTR_BASE_URL = "https://api.vultr.com"
# Vultr caps per_page at 500 (default 100). Fewer requests keeps us well under the ~30 req/s rate limit.
VULTR_PER_PAGE = 500


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Vultr paginates via a body cursor at meta.links.next, replayed as the `cursor` query param.
    # The final page returns an empty string, which the paginator treats as "no next page".
    return JSONResponseCursorPaginator(cursor_path="meta.links.next", cursor_param="cursor")


def get_resource(endpoint: str) -> EndpointResource:
    config = ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        # No server-side time filter exists on any Vultr list endpoint, so we always full-refresh.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": {"per_page": VULTR_PER_PAGE},
        },
        "table_format": "delta",
    }


def vultr_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> Resource:
    config: RESTAPIConfig = {
        "client": {
            "base_url": VULTR_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _cursor_paginator(),
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint)],
    }

    return rest_api_resource(config, team_id, job_id, db_incremental_field_last_value=None)


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the account endpoint to confirm the API key is genuine.

    A single Vultr API key grants full account access (no per-product scoping), so at source-create
    we only need to confirm the token is real. A 403 means the token is valid but the portal's IP
    access-control list is blocking us (or a sub-user's ACL is restricted) — we accept that at
    create time so the source can still be set up; sync-time 403s are surfaced by
    `get_non_retryable_errors`.
    """
    try:
        response = make_tracked_session().get(
            f"{VULTR_BASE_URL}/v2/account",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Vultr API key. Generate a new key in the Vultr customer portal and try again."
    if response.status_code == 403 and schema_name is None:
        return True, None
    if response.status_code == 403:
        return (
            False,
            "Your Vultr API key is being blocked. Check the API key's IP access control list in the Vultr customer portal.",
        )
    return False, f"Unexpected response from Vultr (HTTP {response.status_code})."
