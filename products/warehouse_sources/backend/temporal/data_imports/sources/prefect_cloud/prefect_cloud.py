import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    PAGE_LIMIT,
    PREFECT_CLOUD_ENDPOINTS,
    PrefectCloudEndpointConfig,
)

PREFECT_CLOUD_API_BASE = "https://api.prefect.cloud/api"

# Account and workspace IDs are UUIDs embedded in the request path. Rejecting anything else keeps
# user input from rewriting the path (e.g. `../` traversal into another account's routes).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclasses.dataclass
class PrefectCloudResumeConfig:
    # Row offset of the next page to fetch. 0 means "start from the first page".
    offset: int = 0


def normalize_uuid(value: str, label: str) -> str:
    """Reduce user input to a bare lowercase UUID, raising ``ValueError`` on anything else."""
    cleaned = value.strip().lower()
    if not _UUID_RE.match(cleaned):
        raise ValueError(
            f"Invalid Prefect Cloud {label}: {value!r}. Copy the UUID from your workspace URL: "
            "https://app.prefect.cloud/account/<account ID>/workspace/<workspace ID>."
        )
    return cleaned


def _workspace_url(account_id: str, workspace_id: str) -> str:
    account = normalize_uuid(account_id, "account ID")
    workspace = normalize_uuid(workspace_id, "workspace ID")
    return f"{PREFECT_CLOUD_API_BASE}/accounts/{account}/workspaces/{workspace}"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_after(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC string Prefect's `after_` filters expect.

    Microseconds are truncated, which can only shift the cursor slightly earlier — the re-pulled
    boundary rows are deduped on the primary key at merge.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _resolve_incremental_sort(config: PrefectCloudEndpointConfig, incremental_field: str | None) -> tuple[str, str]:
    """Pick the (filter field, ascending sort) pair, honoring the user's chosen cursor field."""
    if incremental_field and incremental_field in config.incremental_sorts:
        return incremental_field, config.incremental_sorts[incremental_field]
    first = next(iter(config.incremental_sorts))
    return first, config.incremental_sorts[first]


def _build_json_body(
    config: PrefectCloudEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the static POST body (nested filter + sort) sent on every page.

    Prefect's filter endpoints take filter, sort, limit, and offset in the JSON body (not query
    params). The paginator injects `limit`/`offset` per page; this body carries the watermark
    filter and stable sort, and because the paginator mutates the same dict in place the filter
    rides every page (server-side incremental)."""
    body: dict[str, Any] = {}
    sort = config.sort

    if (
        config.filter_key
        and config.incremental_sorts
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        field_name, sort = _resolve_incremental_sort(config, incremental_field)
        body[config.filter_key] = {field_name: {"after_": _format_after(db_incremental_field_last_value)}}

    if sort:
        body["sort"] = sort
    return body


def prefect_cloud_source(
    account_id: str,
    workspace_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PrefectCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PREFECT_CLOUD_ENDPOINTS[endpoint]
    base_url = _workspace_url(account_id, workspace_id)
    json_body = _build_json_body(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Non-secret header only; the API key rides the framework Bearer auth so it's redacted.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # Prefect paginates via `limit`/`offset` in the POST body; no top-level total, so
            # termination is a short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(limit=PAGE_LIMIT, total_path=None, param_location="json"),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "method": "POST",
                    "json": json_body,
                    # Bare-array body: the whole response is the row list (no data_selector).
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(PrefectCloudResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The watermark is baked into the request body above, so the framework's own incremental
        # param injection is unused.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
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
        column_hints=resource.column_hints,
    )


def validate_credentials(account_id: str, workspace_id: str, api_key: str) -> tuple[bool, int | None]:
    """Probe the workspace's flows/filter endpoint to confirm the key reaches the workspace.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if either ID is malformed so the caller can surface a precise message.
    """
    url = f"{_workspace_url(account_id, workspace_id)}/flows/filter"
    try:
        response = make_tracked_session(redact_values=(api_key,)).post(
            url, json={"limit": 1}, headers=_headers(api_key), timeout=10
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
