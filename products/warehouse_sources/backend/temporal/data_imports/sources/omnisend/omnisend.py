import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    OMNISEND_2026_03_15,
    OMNISEND_ENDPOINTS,
    OMNISEND_V3,
    OmnisendWire,
)

OMNISEND_BASE_URL = "https://api.omnisend.com/v3"
OMNISEND_API_BASE_URL = "https://api.omnisend.com/api"

_BASE_URL_BY_VERSION = {
    OMNISEND_V3: OMNISEND_BASE_URL,
    OMNISEND_2026_03_15: OMNISEND_API_BASE_URL,
}

# Raised when a schema is synced on a version that has no list endpoint for it (e.g. a carts
# schema pinned to 2026-03-15, where carts and orders are write-only events).
UNSUPPORTED_ENDPOINT_ERROR = "Omnisend API version has no list endpoint for this table"

# Omnisend allows up to 250 items per page; larger pages mean fewer requests against the
# 400 req/min general rate limit.
PAGE_SIZE = 250


@dataclasses.dataclass(frozen=True)
class OmnisendResumeConfig:
    # Fully-formed next-page URL from the API's `paging.next`; we follow it verbatim.
    next_url: Optional[str] = None
    # Opaque `paging.cursors.after` token for the cursor-paginated 2026-03-15 endpoints.
    cursor: Optional[str] = None


class _OmnisendCursorPaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="paging.cursors.after", cursor_param="after", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        # Omnisend documents `hasMore: false` and a null `after` cursor as equivalent stop signals.
        try:
            has_more = response.json().get("paging", {}).get("hasMore")
        except Exception:
            has_more = None
        if has_more is False:
            self._has_next_page = False


def _base_url(api_version: str) -> str:
    try:
        return _BASE_URL_BY_VERSION[api_version]
    except KeyError:
        raise ValueError(f"Unsupported Omnisend API version: {api_version}")


def _wire(endpoint: str, api_version: str) -> OmnisendWire:
    wire = OMNISEND_ENDPOINTS[endpoint].wires.get(api_version)
    if wire is None:
        raise ValueError(f"{UNSUPPORTED_ENDPOINT_ERROR}: {endpoint} is not available on {api_version}")
    return wire


def _headers(api_version: str) -> dict[str, str]:
    # Auth is supplied via the framework auth config so its value is redacted from logs and raised
    # errors; only non-secret headers are set here.
    headers = {"Accept": "application/json"}
    if api_version != OMNISEND_V3:
        headers["Omnisend-Version"] = api_version
    return headers


@dataclasses.dataclass(frozen=True)
class _AuthHeader:
    name: str
    value: str


def _auth_header(api_key: str, api_version: str) -> _AuthHeader:
    if api_version == OMNISEND_V3:
        return _AuthHeader(name="X-API-KEY", value=api_key)
    return _AuthHeader(name="Authorization", value=f"Omnisend-API-Key {api_key}")


def _client_config(api_key: str, api_version: str, wire: OmnisendWire) -> ClientConfig:
    auth = _auth_header(api_key, api_version)
    paginator: BasePaginator = (
        _OmnisendCursorPaginator()
        if wire.cursor_paginated
        # Omnisend returns a fully-formed next-page URL under `paging.next`; follow it verbatim.
        else JSONResponsePaginator(next_url_path="paging.next")
    )
    return {
        "base_url": _base_url(api_version),
        "headers": _headers(api_version),
        "auth": {"type": "api_key", "api_key": auth.value, "name": auth.name, "location": "header"},
        "paginator": paginator,
        # Pin every request, including `paging.next` links and seeded resume URLs, to the Omnisend
        # host so a tampered link or redirect can't carry the API key elsewhere.
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key is genuine. Returns (is_valid, status_code)."""
    auth = _auth_header(api_key, api_version)
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_base_url(api_version)}/contacts?limit=1",
        headers={auth.name: auth.value, **_headers(api_version)},
        allow_redirects=False,
    )


def omnisend_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
) -> SourceResponse:
    config = OMNISEND_ENDPOINTS[endpoint]
    wire = _wire(endpoint, api_version)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, api_version, wire),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": wire.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": wire.data_key,
                    # A 200 body missing the envelope key means the response shape changed — fail
                    # loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if wire.cursor_paginated and resume.cursor:
                initial_paginator_state = {"cursor": resume.cursor}
            # A next-page URL saved under another version points at that version's base path.
            elif not wire.cursor_paginated and resume.next_url and resume.next_url.startswith(_base_url(api_version)):
                initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if not state:
            return
        if state.get("cursor"):
            resumable_source_manager.save_state(OmnisendResumeConfig(cursor=state["cursor"]))
        elif state.get("next_url"):
            resumable_source_manager.save_state(OmnisendResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Omnisend endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[wire.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
