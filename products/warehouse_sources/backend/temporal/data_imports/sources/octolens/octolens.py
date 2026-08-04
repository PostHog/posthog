import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.settings import (
    OCTOLENS_ENDPOINTS,
    OctolensEndpointConfig,
)

OCTOLENS_BASE_URL = "https://app.octolens.com"
# Documented maximum page size on the mentions feed (1-100, default 20).
PAGE_SIZE = 100
# Cheap credential introspection endpoint: returns the workspace the key is bound to plus its
# effective scopes. Every read-capable key can call it, so it validates the key without needing
# access to any particular table.
AUTH_PROBE_PATH = "/auth"


@dataclasses.dataclass
class OctolensResumeConfig:
    cursor: str


def _api_path(api_version: str, path: str) -> str:
    return f"/api/{api_version}{path}"


def _mentions_body() -> dict[str, Any]:
    # No `filters.startDate`: it filters on the mention's post time, which says nothing about when
    # Octolens collected or last changed the row, so watermarking on it would drop late-collected
    # historical mentions and every later edit to an already-synced row. See settings.py.
    return {
        "limit": PAGE_SIZE,
        # Defaults to false, which silently drops low-relevance mentions. A warehouse copy should
        # mirror everything Octolens collected, so opt in.
        "includeAll": True,
    }


def _paginator(config: OctolensEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    # The cursor rides in the POST body alongside the filters, not the query string.
    return JSONResponseCursorPaginator(
        cursor_path="pagination.nextCursor", cursor_param="cursor", param_location="json"
    )


def _resource(config: OctolensEndpointConfig, api_version: str) -> EndpointResource:
    endpoint: Endpoint = {
        "path": _api_path(api_version, config.path),
        "method": config.method,
        "data_selector": config.data_selector,
        "paginator": _paginator(config),
    }
    if config.method == "post":
        endpoint["json"] = _mentions_body()

    return {
        "name": config.name,
        "table_name": config.name,
        "table_format": "delta",
        # Every Octolens table is full refresh — the API exposes no update-aware cursor.
        "write_disposition": "replace",
        "endpoint": endpoint,
    }


def octolens_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[OctolensResumeConfig],
) -> SourceResponse:
    config = OCTOLENS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": OCTOLENS_BASE_URL,
            "headers": {"Content-Type": "application/json", "Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [_resource(config, api_version)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Fires AFTER a page is yielded, so a crash re-fetches the page we were about to read rather
        # than skipping it — completeness over an occasional replayed row.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(OctolensResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if config.paginated else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, api_version: str) -> tuple[int, Optional[str]]:
    """Probe the credential-introspection endpoint and report `(status, message)`.

    Status mimics HTTP semantics: 200 = key is genuine, 401 = bad/expired key, 403 = valid key
    without the scope, 0 = could not reach or parse Octolens.
    """
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            f"{OCTOLENS_BASE_URL}{_api_path(api_version, AUTH_PROBE_PATH)}",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001 — a credential probe must never raise out of validation
        return 0, f"Could not connect to Octolens: {e}"

    if response.status_code in (401, 403):
        return response.status_code, _error_message(response)

    if not 200 <= response.status_code < 300:
        return response.status_code, _error_message(response) or f"Octolens returned HTTP {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        # A 200 that isn't JSON (a proxy or maintenance page) is not a valid Octolens response.
        return 0, "Octolens returned a non-JSON response"

    if not isinstance(body, dict) or not body.get("organizationId"):
        return 0, "Octolens did not return a workspace for this API key"

    return 200, None


def _error_message(response: Any) -> Optional[str]:
    """Pull `error.message` out of Octolens' error envelope, which every non-2xx response shares."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    return str(message) if message else None
