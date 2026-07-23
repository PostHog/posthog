import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import (
    PAGE_SIZE,
    WORKABLE_ENDPOINTS,
)

# Workable account subdomains are DNS labels — letters, digits and hyphens. Validating this before
# building the URL prevents host injection (e.g. a `subdomain` of `evil.com/` would otherwise retarget
# the request and exfiltrate the stored token).
_SUBDOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")

# Maps the incremental cursor column to Workable's server-side time filter param. The column is
# `updated_at` / `created_at`; the filter is `updated_after` / `created_after`.
_TIME_FILTER_PARAM = {"updated_at": "updated_after", "created_at": "created_after"}


@dataclasses.dataclass
class WorkableResumeConfig:
    # Full `paging.next` URL to fetch next. `None` means start the endpoint from its first page.
    next_url: str | None = None


def _validate_subdomain(subdomain: str) -> str:
    subdomain = (subdomain or "").strip()
    if not _SUBDOMAIN_RE.match(subdomain):
        raise ValueError(
            "Invalid Workable subdomain. Use just the account subdomain from "
            "https://<subdomain>.workable.com (letters, digits and hyphens only)."
        )
    return subdomain


def _base_url(subdomain: str) -> str:
    return f"https://{_validate_subdomain(subdomain)}.workable.com/spi/v3"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp with a `Z` suffix."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sort_mode_for(endpoint: str, should_use_incremental_field: bool, incremental_field: str | None) -> SortMode:
    """Pick the order the pipeline should assume rows arrive in.

    Workable paginates by `since_id` (ascending id, which tracks ascending `created_at`); it has no
    way to sort by `updated_at`. So when the cursor field is `created_at`, rows genuinely arrive in
    ascending cursor order and the watermark can advance per batch (`asc`). When the cursor is
    `updated_at`, arrival order is unrelated to the cursor, so we use `desc` — which defers the
    watermark commit to sync completion — to avoid advancing past unsynced rows on a partial failure.
    """
    if not should_use_incremental_field or not WORKABLE_ENDPOINTS[endpoint].supports_incremental:
        return "asc"
    return "asc" if incremental_field == "created_at" else "desc"


def workable_source(
    subdomain: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkableResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = WORKABLE_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": PAGE_SIZE}

    # Only inject the server-side time filter when the endpoint exposes one and we have a cursor to
    # filter on. `updated_after` / `created_after` are the documented filters; default to `updated_at`
    # so edits to existing rows are picked up. The value is formatted ISO 8601 with a `Z` suffix.
    incremental: Optional[IncrementalConfig] = None
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        field_name = incremental_field or "updated_at"
        filter_param = _TIME_FILTER_PARAM.get(field_name, "updated_after")
        incremental = {"start_param": filter_param, "cursor_path": field_name, "convert": _format_datetime}

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        # Rows are nested under the endpoint's data key (e.g. `{"jobs": [...]}`). A missing key
        # yields an empty page (matching the original `.get(data_key, [])`), so no fail-loud here.
        "data_selector": config.data_key,
        # `paging.next` is a full URL carrying the cursor params; the paginator follows it verbatim
        # and stops when it's absent.
        "paginator": JSONResponsePaginator(next_url_path="paging.next"),
    }
    if incremental is not None:
        endpoint_config["incremental"] = incremental

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            # Auth (Bearer) goes through the framework auth config so the token is redacted from logs
            # and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
        },
        "resource_defaults": {},
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
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(WorkableResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
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
        sort_mode=_sort_mode_for(endpoint, should_use_incremental_field, incremental_field),
    )


def validate_credentials(subdomain: str, api_token: str, path: str = "/jobs") -> tuple[int, bool]:
    """Probe a Workable endpoint. Returns ``(status_code, ok)``; ``status_code`` is ``0`` on a transport error."""
    # Building the URL validates the subdomain and raises ValueError for an invalid one, before any
    # request — the caller surfaces that as a non-transport failure.
    url = f"{_base_url(subdomain)}{path}?{urlencode({'limit': 1})}"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(api_token),
    )
    return status or 0, ok
