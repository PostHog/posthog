import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from requests import Response

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
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Supported PMS API versions. Cloudbeds serves each version at the same host under a
# `/api/<version>` path segment where the segment is the version label verbatim, so the URL is
# built by interpolation rather than a per-version map (every supported label is covered by
# construction). Response shapes, pagination, and Bearer auth are identical across versions.
CLOUDBEDS_API_VERSION_V1_2 = "v1.2"
CLOUDBEDS_API_VERSION_V1_3 = "v1.3"

CLOUDBEDS_API_HOST = "https://api.cloudbeds.com/api"


def cloudbeds_base_url(api_version: str) -> str:
    return f"{CLOUDBEDS_API_HOST}/{api_version}"


# The Accounting API is versioned on its own track, independent of the PMS API pin.
CLOUDBEDS_ACCOUNTING_BASE_URL = "https://api.cloudbeds.com/accounting/v1.0"
# The transactions search caps `limit` at 1100 records per page.
ACCOUNTING_PAGE_SIZE = 1100
# The transactions search requires a base filter, so an open lower bound on transaction_datetime
# selects every posted transaction. The request body never changes between attempts, which keeps a
# saved pageToken valid on resume.
ACCOUNTING_TRANSACTIONS_FILTER: dict[str, Any] = {
    "and": [{"field": "transaction_datetime", "operator": "greater_than_or_equal", "value": "1970-01-01T00:00:00Z"}]
}
ACCOUNTING_TRANSACTIONS_SORT: list[dict[str, str]] = [
    {"field": "transaction_datetime", "direction": "asc"},
    {"field": "id", "direction": "asc"},
]
PROPERTY_ID_REQUIRED_MESSAGE = (
    "Cloudbeds transactions need a property ID. Enter the property ID in the source settings, then sync again."
)


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
    # nextPageToken of the Accounting API transactions search, which pages by an opaque cursor.
    page_token: str | None = None


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
        nested = parent.get(cast("str", flatten_field))
        if not isinstance(nested, list):
            return []
        # Direct access so a missing required parent field (e.g. propertyID) fails fast instead of
        # silently writing None across every flattened child row.
        merged = {key: parent[key] for key in parent_fields}
        return [{**row, **merged} for row in nested]

    return flatten


def _keyed_map(config: CloudbedsEndpointConfig) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """Explode a ``data`` object keyed by property ID (getUsers) into one row per nested item,
    copying the key into ``keyed_by_field``. This is the map-shaped counterpart of ``_flatten_map``."""
    key_field = cast("str", config.keyed_by_field)

    def explode(container: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, items in container.items():
            if not isinstance(items, list):
                continue
            rows.extend({**item, key_field: key} for item in items)
        return rows

    return explode


def cloudbeds_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudbedsResumeConfig],
    api_version: str,
    property_id: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLOUDBEDS_ENDPOINTS[endpoint]
    if config.accounting_api:
        return _accounting_source(
            api_key=api_key,
            config=config,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=api_version,
            property_id=property_id,
        )

    # Group (multi-property) credentials require the property ID to scope reads; single-property
    # credentials can omit it. Sent on every request (the paginator only touches pageNumber).
    params: dict[str, Any] = {}
    if property_id:
        params[config.property_param] = property_id

    if config.stay_window_days is not None:
        # The window is required, and it decides which rate plans the response covers: rates that do
        # not apply to any night in it are left out.
        today = datetime.now(UTC).date()
        params["startDate"] = today.isoformat()
        params["endDate"] = (today + timedelta(days=config.stay_window_days)).isoformat()

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
    elif config.keyed_by_field:
        endpoint_config["data_map"] = _keyed_map(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": cloudbeds_base_url(api_version),
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


def _resolve_property_id(api_key: str, api_version: str) -> str:
    """Read the property ID of a single-property credential from getHotels.

    The Accounting API requires the property in the X-Property-ID header, but single-property
    credentials may leave the property ID field empty.
    """
    response = make_tracked_session(redact_values=(api_key,)).get(
        f"{cloudbeds_base_url(api_version)}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
        timeout=60,
    )
    response.raise_for_status()
    hotels = response.json().get("data") or []
    property_ids = {str(hotel["propertyID"]) for hotel in hotels if hotel.get("propertyID") is not None}
    if len(property_ids) != 1:
        raise ValueError(PROPERTY_ID_REQUIRED_MESSAGE)
    return property_ids.pop()


def _accounting_source(
    api_key: str,
    config: CloudbedsEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudbedsResumeConfig],
    api_version: str,
    property_id: str | None,
) -> SourceResponse:
    resolved_property_id = property_id or _resolve_property_id(api_key, api_version)

    endpoint_config: EndpointResource = {
        "name": config.name,
        "endpoint": {
            "path": config.path,
            "method": "POST",
            "json": {
                "filters": ACCOUNTING_TRANSACTIONS_FILTER,
                "limit": ACCOUNTING_PAGE_SIZE,
                "sort": ACCOUNTING_TRANSACTIONS_SORT,
            },
            "data_selector": "transactions",
            "data_selector_required": True,
        },
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CLOUDBEDS_ACCOUNTING_BASE_URL,
            "headers": {**_headers(), "X-Property-ID": resolved_property_id},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": JSONResponseCursorPaginator(
                cursor_path="nextPageToken",
                cursor_param="pageToken",
                param_location="json",
                raise_on_repeated_cursor=True,
            ),
        },
        "resources": [endpoint_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_token is not None:
            initial_paginator_state = {"cursor": resume.page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(CloudbedsResumeConfig(page_token=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_version: str, property_id: str | None = None) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API key or OAuth access token.

    One probe validates the token itself; per-endpoint OAuth scopes surface at sync time via
    get_non_retryable_errors. 401/403 map to an invalid-key message; any other non-200 reports the
    status; an unreachable probe reports a generic connection failure.
    """
    url = f"{cloudbeds_base_url(api_version)}{DEFAULT_PROBE_PATH}"
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
