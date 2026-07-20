import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.settings import (
    CLOUDBEDS_ENDPOINTS,
    CloudbedsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CLOUDBEDS_BASE_URL = "https://api.cloudbeds.com/api/v1.2"
# List endpoints accept pageSize up to 100 (the default); the largest page minimises round trips
# against Cloudbeds' 5 req/sec property-credential rate limit.
PAGE_SIZE = 100
# Cheap endpoint used to confirm a token is genuine. Every credential (API key or OAuth token) can
# read the properties it is scoped to, so one probe validates the token itself; per-endpoint scopes
# are handled at sync time via get_non_retryable_errors.
DEFAULT_PROBE_PATH = "/getHotels"


@dataclasses.dataclass
class CloudbedsResumeConfig:
    # Next pageNumber to fetch (1-based). Cloudbeds paginates by page number, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes the
    # re-pulled page on the primary key. `None` means start from the first page.
    page: int | None = None


class CloudbedsPageNumberPaginator(PageNumberPaginator):
    """1-based ``pageNumber`` pagination with short-page termination.

    Cloudbeds exposes no usable page total, so a page shorter than the requested ``pageSize`` (or an
    empty one) is the last page — stop there instead of paying one extra empty-page request. Resume
    is inherited from ``PageNumberPaginator`` (``self.page`` points at the next unfetched page).
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="pageNumber")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _headers() -> dict[str, str]:
    # Bearer auth is supplied via the framework auth config so the key is redacted from logs and
    # raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _flatten_map(config: CloudbedsEndpointConfig) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """Explode a parent row's nested list (e.g. getRooms' per-property ``rooms``) into one row each,
    copying the parent's ``flatten_parent_fields`` in — the 1-to-many form of ``data_map``."""
    flatten_field = config.flatten_field
    parent_fields = config.flatten_parent_fields

    def flatten(parent: dict[str, Any]) -> list[dict[str, Any]]:
        nested = parent.get(flatten_field)
        if not isinstance(nested, list):
            return []
        # Direct access so a missing required parent field (e.g. propertyID) fails fast instead of
        # silently writing None across every flattened child row.
        merged = {key: parent[key] for key in parent_fields}
        return [{**row, **merged} for row in nested]

    return flatten


def cloudbeds_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudbedsResumeConfig],
    property_id: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLOUDBEDS_ENDPOINTS[endpoint]

    # Group (multi-property) credentials require propertyID to scope reads; single-property
    # credentials can omit it. Sent on every request (the paginator only touches pageNumber).
    params: dict[str, Any] = {}
    if property_id:
        params["propertyID"] = property_id

    paginator: BasePaginator
    if config.paginated:
        paginator = CloudbedsPageNumberPaginator(PAGE_SIZE)
        params["pageSize"] = PAGE_SIZE
    else:
        paginator = SinglePagePaginator()

    endpoint_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": "data",
            # Cloudbeds wraps rows under `data`; a 200 body without it — a `success: false` error
            # envelope (bad params / missing scope) or a changed shape — fails loud instead of
            # silently syncing 0 rows. A present-but-empty `data` list is still a valid 0-row page.
            "data_selector_required": True,
        },
    }
    if config.flatten_field:
        endpoint_config["data_map"] = _flatten_map(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CLOUDBEDS_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": paginator,
        },
        "resources": [endpoint_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) and merge dedupes the re-pull.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(CloudbedsResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, property_id: str | None = None) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API key or OAuth access token.

    One probe validates the token itself; per-endpoint OAuth scopes surface at sync time via
    get_non_retryable_errors. 401/403 map to an invalid-key message; any other non-200 reports the
    status; an unreachable probe reports a generic connection failure.
    """
    url = f"{CLOUDBEDS_BASE_URL}{DEFAULT_PROBE_PATH}"
    if property_id:
        url = f"{url}?propertyID={property_id}"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Cloudbeds API key"
    if status is None:
        return False, "Could not connect to Cloudbeds"
    return False, f"Cloudbeds returned HTTP {status}"
