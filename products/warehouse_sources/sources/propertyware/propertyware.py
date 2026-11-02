from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.settings import (
    ENDPOINT_PATHS,
    INCREMENTAL_FIELD,
    PARTITION_KEY,
    PRIMARY_KEY,
)

BASE_URL = "https://api.propertyware.com/pw/api/rest/v1"
# Docs: default 100, max 500; a limit above 500 is clamped to 500 server-side, so requesting the
# max up front minimizes the number of pages.
PAGE_SIZE = 500
TOTAL_COUNT_HEADER = "X-Total-Count"


@frozen
class PropertywareResumeConfig:
    offset: int


class PropertywareAuth(AuthConfigBase):
    """Propertyware authenticates with three separate headers, not one.

    `x-propertyware-client-id` / `x-propertyware-client-secret` identify the API key pair and
    `x-propertyware-system-id` scopes it to one organization. The generic `api_key` auth type
    carries a single header, so all three are set here and reported for redaction — the tracked
    session's generic header-name scrubber doesn't know these connector-specific header names.
    """

    def __init__(self, client_id: str, client_secret: str, system_id: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.system_id = system_id

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["x-propertyware-client-id"] = self.client_id
        request.headers["x-propertyware-client-secret"] = self.client_secret
        request.headers["x-propertyware-system-id"] = self.system_id
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.client_id, self.client_secret, self.system_id) if value)


def _format_pw_datetime(value: Any) -> str:
    """Format the incremental cursor as Propertyware's dateAndTime format.

    Docs specify `YYYY-MM-ddTHH:mm:ssXXX` (e.g. `2022-06-28T08:47:13Z`), always UTC.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def propertyware_source(
    client_id: str,
    client_secret: str,
    system_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PropertywareResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config: Endpoint = {
        "path": ENDPOINT_PATHS[endpoint],
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_header=TOTAL_COUNT_HEADER, total_path=None),
        # Propertyware list endpoints return a bare JSON array. A non-list 200 body (an error
        # envelope, an HTML gateway page) must fail loud instead of silently syncing 0 rows.
        "data_selector_required": True,
        "params": {"orderby": f"{INCREMENTAL_FIELD} asc"},
    }

    use_incremental = bool(should_use_incremental_field and db_incremental_field_last_value)
    if use_incremental:
        endpoint_config["incremental"] = {
            "start_param": "lastModifiedDateTimeStart",
            "convert": _format_pw_datetime,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": PropertywareAuth(client_id=client_id, client_secret=client_secret, system_id=system_id),
            # Credentials travel in custom headers, not `Authorization` — `requests` won't strip
            # those on a cross-origin redirect, so pin every sync request to the Propertyware host
            # and refuse to follow a 3xx (mirrors the same guard on the validation probe below).
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saved AFTER a page is yielded so a crash re-yields the last page (merge
        # dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(PropertywareResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[PRIMARY_KEY],
        # We always request `orderby={INCREMENTAL_FIELD} asc`, so rows arrive in ascending order.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[PARTITION_KEY],
    )


def validate_credentials(client_id: str, client_secret: str, system_id: str, path: str = "/health") -> Optional[int]:
    """Return the status code of a cheap authenticated probe, or `None` on transport error.

    `/health` requires the same three headers as every other endpoint, so a genuine key set
    returns 200, a bad one 401, and one without access to the whole account 403.
    """
    url = f"{BASE_URL}{path}"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_id, client_secret, system_id)),
        url,
        auth=PropertywareAuth(client_id=client_id, client_secret=client_secret, system_id=system_id),
        # Credentials travel in custom headers, not `Authorization` — `requests` won't strip
        # those on a cross-origin redirect, so don't follow one.
        allow_redirects=False,
    )
    return status


def endpoint_probe_path(endpoint: str) -> str:
    """Path (with query string) for a cheap single-row probe of one endpoint's access."""
    return f"{ENDPOINT_PATHS[endpoint]}?{urlencode({'limit': 1})}"
