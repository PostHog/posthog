from collections.abc import Callable, Iterator
from functools import partial
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.settings import (
    SECUREFRAME_ENDPOINTS,
    SecureframeEndpointConfig,
)

BASE_URLS = {
    "us": "https://api.secureframe.com",
    "uk": "https://api-uk.secureframe.com",
}
DEFAULT_REGION = "us"
# Secureframe caps list pages at 100 items (also the documented default).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


@frozen
class SecureframeResumeConfig:
    page: int = 1
    # Fan-out endpoints only: the parent kind in progress and its fan-out state.
    parent: Optional[str] = None
    fanout_state: Optional[dict[str, Any]] = None


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS[DEFAULT_REGION])


def _get_headers(api_key: str, api_secret: str) -> dict[str, str]:
    # Secureframe authenticates with the API key and secret joined by a space (no scheme prefix).
    return {
        "Authorization": f"{api_key} {api_secret}",
        "Accept": "application/json",
    }


def _make_session(api_key: str, api_secret: str) -> requests.Session:
    # capture=False keeps Secureframe's credentialed responses out of the shared HTTP sample
    # bucket: they carry personnel, device (serial/MAC/IP), and compliance-evidence fields the
    # generic scrubber can't reliably redact. Requests stay metered and logged; redact_values
    # masks the key/secret from logged URLs. The auth header rides on the session (not the
    # framework `auth` config) so both credential halves are redacted individually.
    return make_tracked_session(
        headers=_get_headers(api_key, api_secret),
        redact_values=(api_key, api_secret),
        capture=False,
    )


def _flatten_resource(obj: Any) -> Optional[dict[str, Any]]:
    """Flatten a JSON:API-style resource envelope into a plain row dict.

    Secureframe wraps each resource as ``{"data": {"id", "type", "attributes": {...}}}``;
    the attributes already carry ``id`` per the API spec, but we backfill it from the
    envelope defensively. Plain dicts pass through untouched.
    """
    if not isinstance(obj, dict):
        return None

    node = obj.get("data", obj)
    if not isinstance(node, dict):
        return None

    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        row = dict(attributes)
        if "id" not in row and node.get("id") is not None:
            row["id"] = node["id"]
        return row

    return node


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        items = payload["data"]
    else:
        items = []

    return [row for row in (_flatten_resource(item) for item in items) if row is not None]


def _map_row(item: Any) -> dict[str, Any] | list[dict[str, Any]]:
    """Per-item reshape wired into the rest_source resource.

    With no ``data_selector`` the framework hands us each element of a top-level array
    (the shape the OpenAPI spec declares) — a single JSON:API envelope or a plain row — which
    we flatten 1:1. A ``{"data": [...]}`` document instead arrives as a single item (the whole
    body wrapped), which we explode into one row per resource. Anything unrecognized drops.
    """
    if not isinstance(item, dict):
        return []

    data_node = item.get("data")
    if isinstance(data_node, list):
        return [row for row in (_flatten_resource(node) for node in data_node) if row is not None]

    row = _flatten_resource(item)
    return row if row is not None else []


class SecureframePaginator(PageNumberPaginator):
    """``page``/``per_page`` pagination that stops on the first page with no rows.

    Secureframe exposes no page-count metadata, and its list bodies come in two shapes (a
    top-level array of JSON:API envelopes, or a ``{"data": [...]}`` document). Emptiness must be
    judged on the flattened rows, not the raw container the generic extractor sees, so
    termination is derived from ``_extract_rows`` of the response body. A short page could just
    mean the server capped ``per_page`` below what we asked for, so it does not end the scan.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            rows: list[Any] = _extract_rows(response.json())
        except Exception:
            rows = []
        super().update_state(response, rows)


def _probe_paths(config: SecureframeEndpointConfig) -> list[str]:
    # A fan-out child has no list of its own, so probe the parent lists that it reads.
    if config.fanout_parents:
        return [SECUREFRAME_ENDPOINTS[parent].path for parent in config.fanout_parents]
    return [config.path]


def _probe_endpoint(session: requests.Session, region: str, path: str) -> int:
    """Fetch a single row from an endpoint and return the HTTP status code."""
    params = {"page": 1, "per_page": 1}
    response = session.get(
        f"{_base_url(region)}{path}?{urlencode(params)}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return response.status_code


def validate_credentials(api_key: str, api_secret: str, region: str, endpoint: str | None = None) -> tuple[bool, bool]:
    """Probe the API and return ``(authenticated, authorized)``.

    Secureframe returns 401 for a bad key/secret pair and 403 when the pair is valid but
    the key's RBAC role can't read the probed resource. At source-create a 403 is
    acceptable (users may only grant the scopes they intend to sync), so callers get both
    signals. Any other failure counts as unauthenticated.
    """
    path = _probe_paths(SECUREFRAME_ENDPOINTS[endpoint])[0] if endpoint else "/users"
    url = f"{_base_url(region)}{path}?{urlencode({'page': 1, 'per_page': 1})}"
    _ok, status = validate_via_probe(lambda: _make_session(api_key, api_secret), url, timeout=REQUEST_TIMEOUT_SECONDS)

    if status == 200:
        return True, True
    if status == 403:
        return True, False
    return False, False


def get_endpoint_permissions(api_key: str, api_secret: str, region: str, endpoints: list[str]) -> dict[str, str | None]:
    permissions: dict[str, str | None] = {}
    session = _make_session(api_key, api_secret)
    for endpoint in endpoints:
        config = SECUREFRAME_ENDPOINTS.get(endpoint)
        if config is None:
            permissions[endpoint] = None
            continue
        permissions[endpoint] = None
        for path in _probe_paths(config):
            try:
                status = _probe_endpoint(session, region, path)
            except Exception:
                # A throttle, 5xx, or network blip is not a denial — report reachable.
                continue
            if status in (401, 403):
                permissions[endpoint] = (
                    f"Your API key's role does not have permission to read {endpoint}. "
                    "Update the role's permissions in Secureframe, or deselect this table."
                )
                break
    return permissions


def _fanout_child_resource(
    client_config: ClientConfig,
    endpoint: str,
    config: SecureframeEndpointConfig,
    parent: str,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_state: Optional[dict[str, Any]],
) -> Resource:
    parent_path = SECUREFRAME_ENDPOINTS[parent].path
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": parent,
                "endpoint": {"path": parent_path, "params": {"per_page": PAGE_SIZE}},
                "data_map": _map_row,
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": f"{parent_path}/{{parent_id}}{config.path}",
                    "params": {"parent_id": {"type": "resolve", "resource": parent, "field": "id"}},
                    # The per-asset list takes no page params and returns every row at once.
                    "paginator": "single_page",
                    # An asset deleted after the parent list was read has nothing left to sync.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "data_map": _map_row,
            },
        ],
    }
    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_state,
    )
    return next(resource for resource in resources if resource.name == endpoint)


def _iter_fanout_pages(
    children: list[tuple[str, Resource]],
    stage_parent: Callable[[str], None],
) -> Iterator[list[dict[str, Any]]]:
    for index, (parent, child) in enumerate(children):
        if index > 0:
            # Every row of the earlier parent kinds is already handed on, so a resume starts here.
            stage_parent(parent)
        yield from child


def _fanout_source(
    client_config: ClientConfig,
    endpoint: str,
    config: SecureframeEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SecureframeResumeConfig],
) -> SourceResponse:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    parents = config.fanout_parents
    start = parents.index(resume.parent) if resume is not None and resume.parent in parents else 0

    def stage_parent(parent: str, state: Optional[dict[str, Any]] = None) -> None:
        resumable_source_manager.save_state(SecureframeResumeConfig(parent=parent, fanout_state=state))

    children = [
        (
            parent,
            _fanout_child_resource(
                client_config,
                endpoint,
                config,
                parent,
                team_id,
                job_id,
                resume_hook=partial(stage_parent, parent),
                initial_state=resume.fanout_state if resume is not None and index == start else None,
            ),
        )
        for index, parent in enumerate(parents)
        if index >= start
    ]
    # The wrapper hands each page on unchanged and holds no rows. As a `Resource` it keeps the
    # framework's checkpoints and safe points.
    resource = Resource(
        partial(_iter_fanout_pages, children, stage_parent),
        name=endpoint,
        hints=children[0][1]._hints,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def secureframe_source(
    api_key: str,
    api_secret: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SecureframeResumeConfig],
) -> SourceResponse:
    config = SECUREFRAME_ENDPOINTS[endpoint]
    client_config: ClientConfig = {
        "base_url": _base_url(region),
        # A capture=False, credential-redacting session (see _make_session); the auth header
        # rides on it rather than the framework `auth` config.
        "session": _make_session(api_key, api_secret),
        "paginator": SecureframePaginator(base_page=1),
    }

    if config.fanout_parents:
        return _fanout_source(client_config, endpoint, config, team_id, job_id, resumable_source_manager)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PAGE_SIZE},
                },
                "data_map": _map_row,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": max(resume.page, 1)}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(SecureframeResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Secureframe endpoint is full refresh — no server-side timestamp filter
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
