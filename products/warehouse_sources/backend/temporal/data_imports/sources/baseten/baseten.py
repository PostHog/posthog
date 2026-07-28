import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import (
    BASETEN_ENDPOINTS,
    BasetenEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BASETEN_BASE_URL = "https://api.baseten.co"
# Cursor-paginated endpoints (users, model_apis) accept a `limit`; the entity endpoints ignore it.
PAGE_SIZE = 100


@dataclasses.dataclass
class BasetenResumeConfig:
    # Cursor for the current page of a cursor-paginated endpoint (users, model_apis).
    cursor: str | None = None
    # Legacy fan-out bookmark (next parent id) from the pre-rest_source implementation. Kept so
    # previously saved states still parse; no longer written. A legacy bookmark can't be translated
    # into `fanout_state`, so such a resume restarts the fan-out from the top — these are
    # full-refresh tables, so at worst rows are re-appended once.
    parent_id: str | None = None
    # Framework fan-out checkpoint: {"completed": [child_path, ...], "current": ..., "child_state": ...}.
    fanout_state: dict[str, Any] | None = None


class BasetenCursorPaginator(BasePaginator):
    """Cursor+limit pagination: {"items": [...], "pagination": {"has_more": bool, "cursor": str}}.

    `has_more` is authoritative — the API may still echo a cursor on the terminal page, so a plain
    cursor-path paginator could loop; only follow the cursor while `has_more` is true.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[str] = None

    def _inject(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["cursor"] = self._cursor

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        if self._cursor is not None:
            self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            pagination = response.json().get("pagination") or {}
        except Exception:
            pagination = {}
        next_cursor = pagination.get("cursor") if pagination.get("has_more") else None
        if next_cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._cursor is not None:
            self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _client_config(api_key: str) -> ClientConfig:
    # Auth (Bearer) goes through the framework auth config so the key is redacted from logs and
    # captured samples; only the non-secret Accept header is set here.
    return {
        "base_url": BASETEN_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def _flatten_map(flatten_key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Lift a nested object (e.g. instance_type_prices' `instance_type`) up into the root."""

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(row.get(flatten_key), dict):
            nested = row.pop(flatten_key)
            # Root-level siblings (e.g. `price`) take precedence over nested keys on collision.
            return {**nested, **row}
        return row

    return _map


def _rename_parent_fields_map(
    parent_name: str, include_from_parent_fields: dict[str, str]
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Rename the framework's `_<parent>_<field>` injected columns to the original child columns."""
    key_map = {f"_{parent_name}_{src}": dst for src, dst in include_from_parent_fields.items()}

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        for prefixed_key, target_key in key_map.items():
            if prefixed_key in row:
                row[target_key] = row.pop(prefixed_key)
        return row

    return _map


def _build_flat_resource(
    api_key: str,
    config: BasetenEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BasetenResumeConfig],
) -> Resource:
    """Top-level endpoint: either a single unpaginated request or cursor+limit pagination."""
    endpoint: Endpoint = {
        "path": config.path,
        # Missing data key yields 0 rows (matching the API contract that the key is always present
        # on success); an empty array is a legit zero-row response either way.
        "data_selector": config.data_key,
    }

    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    initial_paginator_state: Optional[dict[str, Any]] = None

    if config.paginated:
        endpoint["params"] = {"limit": PAGE_SIZE}
        endpoint["paginator"] = BasetenCursorPaginator()

        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; saved AFTER a page is yielded so a crash
            # re-yields the last page rather than skipping it. These are full-refresh tables
            # (append writes, no primary-key merge), so a resumed run can re-append at most the
            # one in-flight page — bounded, and cleared by the next clean full refresh.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(BasetenResumeConfig(cursor=state["cursor"]))

        resume_hook = save_checkpoint
    else:
        endpoint["paginator"] = SinglePagePaginator()

    resource_config: EndpointResource = {"name": config.name, "endpoint": endpoint}
    if config.flatten_key:
        resource_config["data_map"] = _flatten_map(config.flatten_key)

    rest_config: RESTAPIConfig = {"client": _client_config(api_key), "resources": [resource_config]}
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def _build_fan_out_resource(
    api_key: str,
    config: BasetenEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BasetenResumeConfig],
) -> Resource:
    """Iterate an unpaginated parent list and fetch this child endpoint once per parent row."""
    assert config.fan_out_parent is not None
    parent_config = BASETEN_ENDPOINTS[config.fan_out_parent]
    include_from_parent_fields = config.fan_out_include_parent_fields or {}

    parent_resource: EndpointResource = {
        "name": parent_config.name,
        "endpoint": {
            "path": parent_config.path,
            "data_selector": parent_config.data_key,
            "paginator": SinglePagePaginator(),
        },
    }
    child_resource: EndpointResource = {
        "name": config.name,
        "endpoint": {
            "path": config.path,
            "data_selector": config.data_key,
            "paginator": SinglePagePaginator(),
            "params": {
                config.fan_out_path_param: {
                    "type": "resolve",
                    "resource": parent_config.name,
                    "field": config.fan_out_parent_field,
                },
            },
            # A parent deleted between enumeration and the child fetch 404s — skip it rather than
            # fail the whole sync. 429/5xx are retried by the client before hooks run, and any
            # other 4xx still raises.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        # Copies parent context onto each child row so the linkage column is always present (and
        # the composite primary key stays unique table-wide).
        "include_from_parent": list(include_from_parent_fields),
        "data_map": _rename_parent_fields_map(parent_config.name, include_from_parent_fields),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework checkpoints after each parent completes; a resumed run re-fetches the
        # (small) parent list and skips parents already fully synced. Full-refresh tables, so a
        # crash mid-parent can at most re-append that parent's children — bounded, and cleared by
        # the next clean full refresh.
        if state:
            resumable_source_manager.save_state(BasetenResumeConfig(fanout_state=state))

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [parent_resource, child_resource],
    }
    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    parent = next(r for r in resources if r.name == parent_config.name)
    child = next(r for r in resources if r.name == config.name)

    # Drop parents missing the fan-out id. Stringifying a missing id would build a bogus child path
    # (e.g. `/v1/models/None/deployments`) and could sync child rows keyed to a literal "None".
    parent.add_filter(lambda item: item.get(config.fan_out_parent_field) not in (None, ""))

    return child


def validate_credentials(api_key: str) -> bool:
    # /v1/users/me is the cheapest workspace-scoped probe and doesn't depend on any resource existing.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASETEN_BASE_URL}/v1/users/me",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok


def baseten_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BasetenResumeConfig],
) -> SourceResponse:
    config = BASETEN_ENDPOINTS[endpoint]

    if config.fan_out_parent:
        resource = _build_fan_out_resource(api_key, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _build_flat_resource(api_key, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
