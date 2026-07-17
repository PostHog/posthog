import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import (
    GURU_ENDPOINTS,
    GuruEndpointConfig,
)

GURU_BASE_URL = "https://api.getguru.com/api/v1"
GURU_API_HOST = "api.getguru.com"


@dataclasses.dataclass
class GuruResumeConfig:
    # Guru pagination follows a `Link: <url>; rel="next-page"` header whose URL is
    # self-contained (opaque continuation token), so the URL is all we persist.
    next_url: str


def _format_last_modified(value: Any) -> str:
    """Format an incremental cursor for a Guru Query Language date filter.

    GQL absolute dates require an ISO 8601 value with an explicit timezone
    (e.g. 2016-01-01T00:00:00+00:00)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_params(
    config: GuruEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, str]:
    params = dict(config.extra_params)

    if not config.incremental_fields:
        return params

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or config.incremental_fields[0]["field"]
        params["q"] = f"{cursor_field} >= {_format_last_modified(db_incremental_field_last_value)}"
        # Ascending order on the cursor field so the incremental watermark advances
        # monotonically as pages are consumed.
        params["sortField"] = cursor_field
        params["sortOrder"] = "asc"
    else:
        # Full refresh: sort on the stable creation date so rows modified mid-sync
        # don't move across page boundaries (lastModified is Guru's default sort).
        params["sortField"] = "dateCreated"
        params["sortOrder"] = "asc"

    return params


def _normalize_member(item: dict[str, Any]) -> dict[str, Any]:
    # Team member rows nest the identifying email under `user`; copy it to the top
    # level so it can serve as the primary key. Use direct access so a member missing
    # the email surfaces a fast KeyError instead of a row with a null primary key.
    if "email" not in item and isinstance(item.get("user"), dict):
        return {**item, "email": item["user"]["email"]}
    return item


def validate_credentials(username: str, api_token: str) -> bool:
    """Confirm the user token is valid. /whoami is a cheap authenticated probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{GURU_BASE_URL}/whoami",
        auth=HTTPBasicAuth(username, api_token),
    )
    return ok


def guru_source(
    username: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GuruResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GURU_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    resource_config: dict[str, Any] = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            # Guru returns a bare JSON array; a non-list 200 body means the response shape
            # changed — fail loud instead of wrapping the stray object as a single row.
            "data_selector_required": True,
        },
    }
    if endpoint == "members":
        resource_config["data_map"] = _normalize_member

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GURU_BASE_URL,
            "auth": {"type": "http_basic", "username": username, "password": api_token},
            # Guru paginates via `Link: <url>; rel="next-page"` with an opaque continuation token.
            "paginator": HeaderLinkPaginator(links_next_key="next-page"),
            # The next-page/resume URLs are server-controlled; pin them to the Guru API host and
            # refuse redirects so a tampered link can't move the credentialed request off-host and
            # leak the Basic auth credentials (SSRF). Empty list => same host as base_url only.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(GuruResumeConfig(next_url=state["next_url"]))

    # Incremental filtering is server-side and already baked into `params` above, so the
    # framework's incremental injection is unused here.
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
