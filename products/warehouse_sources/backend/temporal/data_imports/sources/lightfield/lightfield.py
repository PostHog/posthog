from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import (
    LIGHTFIELD_ENDPOINTS,
    LIGHTFIELD_PAGE_SIZE,
)

LIGHTFIELD_BASE_URL = "https://api.lightfield.app"
REQUEST_TIMEOUT_SECONDS = 30


def _version_headers(api_version: str) -> dict[str, str]:
    # Every Lightfield request must carry the dated `Lightfield-Version` header.
    return {
        "Lightfield-Version": api_version,
        "Accept": "application/json",
    }


def lightfield_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
) -> SourceResponse:
    endpoint_config = LIGHTFIELD_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": LIGHTFIELD_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": _version_headers(api_version),
            # `totalCount` reflects the matching records at request time; the paginator also
            # stops on a short page, which the docs give as the canonical termination signal.
            "paginator": OffsetPaginator(limit=LIGHTFIELD_PAGE_SIZE, total_path="totalCount"),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [
            {
                "name": endpoint_config.name,
                "table_name": endpoint_config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": endpoint_config.path,
                    "data_selector": "data",
                },
                "table_format": "delta",
            }
        ],
    }

    resource = rest_api_resource(config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
    )


def check_token(api_key: str, api_version: str) -> tuple[bool, list[str] | None, str | None]:
    """Probe `/v1/auth/validate` (no scope required). Returns (valid, granted scopes, error)."""
    session = make_tracked_session(redact_values=(api_key,))
    res = session.get(
        f"{LIGHTFIELD_BASE_URL}/v1/auth/validate",
        headers={"Authorization": f"Bearer {api_key}", **_version_headers(api_version)},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if res.status_code == 401:
        return False, None, "Invalid Lightfield API key. Check the key and try again."
    if res.status_code != 200:
        return False, None, f"Lightfield returned an unexpected status ({res.status_code}) while validating the key."

    body: dict[str, Any] = res.json()
    if not body.get("active", False):
        return False, None, "This Lightfield API key is no longer active. Generate a new key and reconnect."

    raw_scopes = body.get("scopes")
    scopes = [str(scope) for scope in raw_scopes] if isinstance(raw_scopes, list) else None
    return True, scopes, None
