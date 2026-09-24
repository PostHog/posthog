import logging
import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.settings import (
    COASSEMBLE_ENDPOINTS,
    PAGE_SIZE,
    CoassembleEndpointConfig,
)
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
    BasePaginator,
    PageNumberPaginator,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

logger = logging.getLogger(__name__)

# Single shared host — Coassemble has no per-workspace subdomains.
COASSEMBLE_BASE_URL = "https://api.coassemble.com/api/v1/headless"
# Hard cap on child pages per fan-out parent (page_size * cap rows) so a paging bug on the vendor
# side can never produce an unbounded scan of a single parent.
MAX_FAN_OUT_PAGES_PER_PARENT = 1_000
# Cheap list probe used to confirm credentials are genuine. The workspace API key is
# workspace-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/courses"

# The only endpoint that can carry a bookmark saved before the fan-out moved onto the framework.
LEGACY_FAN_OUT_ENDPOINT = "course_trackings"


@dataclasses.dataclass(frozen=True)
class CoassembleResumeConfig:
    # Next page to fetch (0-indexed page-number pagination). Deterministic, so a crashed sync
    # resumes from the page after the last one yielded; merge dedupes the re-pulled page on the
    # primary key.
    next_page: int = 0
    # Pre-framework trackings fan-out bookkeeping. Kept with defaults so previously saved state
    # still parses (and is translated into fanout_state on load); no longer written.
    completed_course_ids: list[int] = dataclasses.field(default_factory=list)
    current_course_id: int | None = None
    # Framework fan-out resume state for a fan-out endpoint:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


class CoassemblePageNumberPaginator(PageNumberPaginator):
    """0-indexed page-number pagination where every list endpoint serves fixed-length pages, so a
    short page marks the end of the collection (we always request the endpoint's page size — no
    extra empty-page request). ``max_pages`` caps how many pages one paginate call fetches (the
    runaway-parent guard for fan-outs); the paginator is deep-copied per fan-out parent, so the cap
    is per parent.
    """

    def __init__(self, page_size: int = PAGE_SIZE, max_pages: Optional[int] = None) -> None:
        super().__init__(base_page=0, page_param="page")
        self.page_size = page_size
        self.max_pages = max_pages
        self._pages_fetched = 0

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        self._pages_fetched += 1
        if data is not None and len(data) < self.page_size:
            self._has_next_page = False
        if self.max_pages is not None and self._pages_fetched >= self.max_pages and self._has_next_page:
            logger.warning(
                "Coassemble: hit fan-out page cap (%s); remaining rows for this parent are skipped this sync",
                self.max_pages,
            )
            self._has_next_page = False


def _auth_header_value(workspace_id: str, api_key: str) -> str:
    # Vendor-specific scheme documented at https://developers.coassemble.com/get-started —
    # Coassemble rejects standard schemes (Bearer etc.) with "Invalid Authorization header".
    return f"COASSEMBLE:{workspace_id}:{api_key}"


def _client_config(workspace_id: str, api_key: str) -> ClientConfig:
    # The credential travels via framework api_key auth (not a hand-built header) so its value is
    # registered for redaction wherever it surfaces in logs; only non-secret headers go here.
    return {
        "base_url": COASSEMBLE_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {
            "type": "api_key",
            "api_key": _auth_header_value(workspace_id, api_key),
            "name": "Authorization",
            "location": "header",
        },
    }


def _paginator(config: CoassembleEndpointConfig, max_pages: Optional[int] = None) -> BasePaginator:
    if config.page_size is None:
        return SinglePagePaginator()
    return CoassemblePageNumberPaginator(page_size=config.page_size, max_pages=max_pages)


def _endpoint_resource(config: CoassembleEndpointConfig, max_pages: Optional[int] = None) -> EndpointResource:
    # Endpoints document a JSON array (or, where `data_selector` is set, an array under one
    # envelope key); a 200 body of any other shape means the response shape changed — fail loud
    # instead of silently syncing 0 rows.
    endpoint: Endpoint = {
        "path": config.path,
        "params": {"length": config.page_size} if config.page_size is not None else {},
        "paginator": _paginator(config, max_pages),
        "data_selector": config.data_selector,
        "data_selector_required": True,
    }
    return {"name": config.name, "endpoint": endpoint}


def _standard_resource(
    client_config: ClientConfig,
    config: CoassembleEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[CoassembleResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {"client": client_config, "resources": [_endpoint_resource(config)]}

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.next_page > 0:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER a page is yielded so
        # a crash re-fetches the in-flight page (merge dedupes re-pulled rows) rather than skipping it.
        if state and state.get("page") is not None:
            manager.save_state(CoassembleResumeConfig(next_page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _stamp_parent_value(parent_name: str, parent_field: str, column: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    injected_key = make_parent_key_name(parent_name, parent_field)

    def stamp(row: dict[str, Any]) -> dict[str, Any]:
        value = row.pop(injected_key, None)
        if value is not None:
            row[column] = value
        return row

    return stamp


def _legacy_child_path(course_id: int) -> str:
    return COASSEMBLE_ENDPOINTS[LEGACY_FAN_OUT_ENDPOINT].path.format(id=course_id)


def _translate_legacy_fanout_state(resume: CoassembleResumeConfig) -> Optional[dict[str, Any]]:
    """Translate a pre-framework trackings bookmark into the framework's fan-out resume shape.

    The old bookkeeping tracked course ids (completed + the one being paged) and the next page of
    the current course; the framework keys the same information by resolved child path, so the
    translation is exact and a pre-migration crash resumes precisely where it left off.
    """
    if not resume.completed_course_ids and resume.current_course_id is None:
        return None
    current = _legacy_child_path(resume.current_course_id) if resume.current_course_id is not None else None
    return {
        "completed": [_legacy_child_path(course_id) for course_id in resume.completed_course_ids],
        "current": current,
        "child_state": {"page": resume.next_page} if current is not None else None,
    }


def _initial_fan_out_state(
    config: CoassembleEndpointConfig, manager: ResumableSourceManager[CoassembleResumeConfig]
) -> Optional[dict[str, Any]]:
    if not manager.can_resume():
        return None
    resume = manager.load_state()
    if resume is None:
        return None
    if resume.fanout_state is not None:
        return resume.fanout_state
    if config.name != LEGACY_FAN_OUT_ENDPOINT:
        return None
    return _translate_legacy_fanout_state(resume)


def _fan_out_resource(
    client_config: ClientConfig,
    config: CoassembleEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[CoassembleResumeConfig],
) -> Resource:
    """Fan out over a parent endpoint, listing the child rows per parent and stamping the parent
    reference onto each row.

    Full refresh — re-pulled rows on resume are deduped by the endpoint's primary key on merge.
    """
    fan_out = config.fan_out
    assert fan_out is not None
    parent_config = COASSEMBLE_ENDPOINTS[fan_out.parent]

    child = _endpoint_resource(config, max_pages=MAX_FAN_OUT_PAGES_PER_PARENT)
    child_endpoint = child["endpoint"]
    assert isinstance(child_endpoint, dict)
    child_endpoint["params"] = {
        **(child_endpoint.get("params") or {}),
        fan_out.param: {"type": "resolve", "resource": parent_config.name, "field": fan_out.resolve_field},
    }
    child["include_from_parent"] = [fan_out.resolve_field]
    child["data_map"] = _stamp_parent_value(parent_config.name, fan_out.resolve_field, fan_out.stamp_column)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [_endpoint_resource(parent_config), child],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(CoassembleResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=_initial_fan_out_state(config, manager),
    )
    return next(r for r in resources if r.name == config.name)


def coassemble_source(
    workspace_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CoassembleResumeConfig],
) -> SourceResponse:
    config = COASSEMBLE_ENDPOINTS[endpoint]
    client_config = _client_config(workspace_id, api_key)

    if config.fan_out is not None:
        resource = _fan_out_resource(client_config, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _standard_resource(client_config, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(workspace_id: str, api_key: str) -> tuple[bool, str | None]:
    # A bad or revoked credential is rejected with 401/403 — the only conclusive "invalid" signals.
    # Transport failures and unexpected statuses are inconclusive and keep their own messages.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{COASSEMBLE_BASE_URL}{DEFAULT_PROBE_PATH}?page=0&length=1",
        headers={"Authorization": _auth_header_value(workspace_id, api_key), "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Coassemble workspace ID or API key"
    if status is None:
        return False, "Could not connect to Coassemble"
    return False, f"Coassemble returned HTTP {status}"
