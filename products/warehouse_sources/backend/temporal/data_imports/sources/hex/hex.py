import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.settings import (
    HEX_ENDPOINTS,
    HexEndpointConfig,
)

DEFAULT_WORKSPACE_HOST = "app.hex.tech"
HOST_NOT_ALLOWED_ERROR = "Hex workspace URL is not allowed"


class HexHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class HexResumeConfig:
    # Opaque paginator resume state: `{"cursor": ...}` for cursor-paginated endpoints, or the
    # framework's fan-out checkpoint (`{"completed": [...], "current": ..., "child_state": ...}`)
    # for project_runs.
    paginator_state: dict[str, Any]


def normalize_workspace_host(workspace_url: Optional[str]) -> str:
    """Turn whatever the user typed into a bare Hex host.

    Accepts values like ``acme.hex.tech``, ``https://acme.hex.tech/``, or
    ``acme.hex.tech/api/v1`` and returns ``acme.hex.tech``. Blank means the Hex
    multi-tenant cloud (``app.hex.tech``).
    """
    host = (workspace_url or "").strip()
    if not host:
        return DEFAULT_WORKSPACE_HOST
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0]
    return host.strip() or DEFAULT_WORKSPACE_HOST


def _base_url(workspace_url: Optional[str]) -> str:
    return f"https://{normalize_workspace_host(workspace_url)}/api"


class HexCursorPaginator(JSONResponseCursorPaginator):
    """Hex cursor pagination: the next-page token arrives in ``pagination.after`` and is sent
    back as the ``after`` query param. An empty page ends pagination even if a token is present,
    so an API quirk can't loop us forever."""

    def __init__(self) -> None:
        super().__init__(cursor_path="pagination.after", cursor_param="after")

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def validate_credentials(
    workspace_url: Optional[str], api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe ListProjects with limit=1 to confirm the bearer token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may lack
    a permission for this particular probe. A scoped probe (``schema_name`` set) treats 403 as a
    hard failure.
    """
    host = normalize_workspace_host(workspace_url)
    if not re.match(r"^[A-Za-z0-9.\-]+$", host):
        return False, "Invalid Hex workspace URL"

    # The workspace host is customer-controlled (single-tenant deployments), so block hosts that
    # resolve to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"https://{host}/api/v1/projects"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF).
        response = make_tracked_session(redact_values=(api_key,)).get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            params={"limit": 1},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Hex API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing permission for this probe — let source creation through.
            return True, None
        return False, "Hex API token lacks the required permissions for this endpoint"

    try:
        body = response.json()
        return False, str(body.get("reason") or body.get("message") or response.text)
    except Exception:
        return False, response.text


def _endpoint_resource(config: HexEndpointConfig) -> EndpointResource:
    params: dict[str, Any] = dict(config.params)
    if config.pagination == "cursor":
        # The offset paginator injects limit/offset itself; cursor endpoints carry limit here.
        params["limit"] = config.page_size
        paginator: Any = HexCursorPaginator()
    else:
        # Runs responses carry no total count — pagination stops on a short or empty page.
        paginator = OffsetPaginator(limit=config.page_size, total_path=None)

    if config.parent is not None:
        params[config.resolve_param or ""] = {
            "type": "resolve",
            "resource": config.parent,
            "field": config.resolve_field,
        }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
            "paginator": paginator,
        },
        "table_format": "delta",
    }
    return resource


def hex_source(
    api_key: str,
    workspace_url: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HexResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HEX_ENDPOINTS[endpoint]

    client: ClientConfig = {
        "base_url": _base_url(workspace_url),
        # The bearer token rides the framework auth config so it is redacted from logs and
        # raised error messages.
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        # A validated host could 3xx to an internal address; refuse to follow redirects (SSRF).
        "allow_redirects": False,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's something to resume to; save AFTER a page is yielded so a
        # crash re-fetches that page (merge dedupes) rather than skipping data.
        if state:
            resumable_source_manager.save_state(HexResumeConfig(paginator_state=state))

    if config.parent is not None:
        rest_config: RESTAPIConfig = {
            "client": client,
            "resource_defaults": {},
            "resources": [_endpoint_resource(HEX_ENDPOINTS[config.parent]), _endpoint_resource(config)],
        }
        resources = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        resource = next(r for r in resources if getattr(r, "name", None) == endpoint)
    else:
        resource = rest_api_resource(
            {"client": client, "resource_defaults": {}, "resources": [_endpoint_resource(config)]},
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    def items() -> Iterator[list[Any]]:
        # Re-check at run time (not just at source-create) in case the workspace URL was edited
        # or now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(normalize_workspace_host(workspace_url), team_id)
        if not host_ok:
            raise HexHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(config.primary_keys),
        sort_mode=config.sort_mode,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
