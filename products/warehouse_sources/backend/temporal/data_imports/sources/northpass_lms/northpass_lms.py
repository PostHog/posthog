import dataclasses
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.settings import (
    NORTHPASS_ENDPOINTS,
    NorthpassEndpointConfig,
)

NORTHPASS_BASE_URL = "https://api.northpass.com/v2"
# Northpass serves every account from this single shared host (no per-account subdomains). Pinning
# every request — including the JSON:API `links.next` pagination URL (attacker-controlled if the
# upstream is spoofed) — to this host keeps the credentialed request from leaking the key off-host.
NORTHPASS_HOST = "api.northpass.com"
# Northpass doesn't publish its max page size; 100 is a conventional cap that keeps payloads small.
PAGE_SIZE = 100


@dataclasses.dataclass
class NorthpassResumeConfig:
    # Top-level endpoints: full URL of the next JSON:API page (`links.next`). None means "start from
    # the first page".
    next_url: str | None = None
    # Deprecated fan-out bookmark from the pre-framework transport. Retained (with a default) so
    # state saved by the old implementation still rehydrates via ``dataclass(**saved)``; new fan-out
    # runs store their cursor in ``fanout_state`` instead.
    parent_id: str | None = None
    # Fan-out endpoints: the framework's dependent-resource resume cursor —
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    # Parents already fully synced are skipped by path; the in-progress parent resumes its page cursor.
    fanout_state: dict[str, Any] | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{NORTHPASS_BASE_URL}{path}"
    return f"{base}?{urlencode(params)}" if params else base


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Promote a JSON:API resource's ``attributes`` to the root, keeping ``id``/``type``/``relationships``.

    The per-item ``links`` block is dropped (it's only self/action hyperlinks).
    """
    row = dict(item)
    attributes = row.pop("attributes", None)
    row.pop("links", None)
    if isinstance(attributes, dict):
        row.update(attributes)
    return row


def _make_child_flattener(parent_name: str, parent_id_field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Flatten a fan-out child row and rename its injected parent id.

    ``include_from_parent=["id"]`` injects the parent id under ``_{parent_name}_id``; rename it to the
    endpoint's ``parent_id_field`` (part of the child primary key) so the parent id always wins over
    any same-named attribute — matching the old transport's ``row.update(extra)`` ordering.
    """
    prefixed_key = make_parent_key_name(parent_name, "id")

    def _flatten(item: dict[str, Any]) -> dict[str, Any]:
        row = _flatten_item(item)
        if prefixed_key in row:
            row[parent_id_field] = row.pop(prefixed_key)
        return row

    return _flatten


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": NORTHPASS_BASE_URL,
        # Auth (the API key) rides in the framework auth config so its value is redacted from logs and
        # raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
        # JSON:API paginates via a `links.next` URL embedded in the response body.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
        # Pin every request to Northpass's host and refuse redirects, so a spoofed `next` link or a
        # 30x can't forward the credentialed X-Api-Key header off-host.
        "allowed_hosts": [NORTHPASS_HOST],
        "allow_redirects": False,
    }


def _top_level_source(
    api_key: str,
    endpoint: str,
    config: NorthpassEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    # A 200 without `data` is treated as an empty page (old transport used
                    # `.get("data", [])`), so no data_selector_required here.
                    "data_selector": "data",
                },
                "data_map": _flatten_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(NorthpassResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_source(
    api_key: str,
    endpoint: str,
    config: NorthpassEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    if config.fan_out_parent is None or config.parent_id_field is None:
        raise ValueError(f"_fan_out_source called with non-fan-out config: {config.name}")
    parent_name = config.fan_out_parent
    parent_config = NORTHPASS_ENDPOINTS[parent_name]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": parent_name,
                "endpoint": {
                    "path": parent_config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                },
            },
            {
                "name": endpoint,
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "parent_id": {"type": "resolve", "resource": parent_name, "field": "id"},
                        "limit": PAGE_SIZE,
                    },
                    "data_selector": "data",
                    # A parent deleted between enumeration and this fetch 404s; treat that child page
                    # as a valid empty page and move on to the next parent rather than failing the sync.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "data_map": _make_child_flattener(parent_name, config.parent_id_field),
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(NorthpassResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    # Only the child rows are emitted; the parent list is iterated internally to drive the fan-out.
    return next(resource for resource in resources if resource.name == endpoint)


def northpass_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NORTHPASS_ENDPOINTS[endpoint]

    if config.fan_out_parent is not None:
        resource = _fan_out_source(
            api_key, endpoint, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )
    else:
        resource = _top_level_source(
            api_key, endpoint, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        _build_url("/courses", {"limit": 1}),
        headers=_headers(api_key),
    )
    return ok, status
