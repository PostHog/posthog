import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import TREMENDOUS_ENDPOINTS

# Sandbox and production are separate hosts with separate API keys.
TREMENDOUS_BASE_URLS: dict[str, str] = {
    "production": "https://www.tremendous.com/api/v2",
    "sandbox": "https://testflight.tremendous.com/api/v2",
}
# Cheap authenticated probe used to confirm an API key is genuine. The key is organization-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/organizations"
# Only /orders exposes a server-side timestamp filter; it is inclusive (`created_at[gte]`), so the
# watermark row itself is re-fetched — merge dedupes it on the primary key.
INCREMENTAL_START_PARAM = "created_at[gte]"


@dataclasses.dataclass
class TremendousResumeConfig:
    # Number of rows already yielded for the current offset/limit page chain. Tremendous paginates
    # by creation date DESC, so rows created mid-sync shift the window and can re-appear on a later
    # page — merge dedupes them on `id`; rows are never skipped.
    offset: int = 0


def base_url_for_environment(environment: str) -> str:
    return TREMENDOUS_BASE_URLS.get(environment, TREMENDOUS_BASE_URLS["production"])


def _to_iso_datetime(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the ISO 8601 string `created_at[gte]` expects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def tremendous_source(
    api_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TremendousResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = TREMENDOUS_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "path": config.path,
        # List responses wrap records under the plural resource name, e.g. {"orders": [...]}.
        "data_selector": config.data_key,
        # A 200 body that isn't the expected {data_key: [...]} shape is treated as transient and
        # retried — mirrors the hand-rolled implementation's retryable unexpected-payload guard.
        "data_selector_malformed_retryable": True,
    }

    if config.paginated:
        # Termination is a short/empty page (OffsetPaginator default); resume by row offset.
        endpoint_config["paginator"] = OffsetPaginator(limit=config.page_size, total_path=None)
    else:
        # Members, campaigns, products, and funding sources return the whole collection at once.
        endpoint_config["paginator"] = SinglePagePaginator()

    incremental_value: Any = None
    if should_use_incremental_field and config.incremental_fields:
        # Server-side `created_at[gte]` filter applied on every page, so pagination stays bounded to
        # the window. Empty/None watermark drops the param (rest_client omits None-valued params).
        endpoint_config["incremental"] = {
            "start_param": INCREMENTAL_START_PARAM,
            "cursor_path": "created_at",
            "convert": _to_iso_datetime,
        }
        incremental_value = db_incremental_field_last_value

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url_for_environment(environment),
            "headers": {"Accept": "application/json"},
            # Framework auth so the Bearer key is redacted from logs and error messages.
            "auth": {"type": "bearer", "token": api_key},
            # Pin redirects off so the Bearer key never replays to a host Tremendous redirects us to.
            "allow_redirects": False,
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
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-fetches from the next page; merge dedupes any
        # re-pulled rows on the primary key. A short/empty page reports no next page → nothing saved.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(TremendousResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        incremental_value,
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
        # Tremendous lists are ordered by creation date DESC and expose no sort param, so the
        # incremental watermark is finalized at the end of a completed sync.
        sort_mode="desc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, environment: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API key.

    The key is organization-wide, so one probe validates access to every list endpoint. 401/403 map
    to a bad-key message; any other non-200 surfaces the status; a transport failure is "not
    validated".
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{base_url_for_environment(environment)}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Tremendous API key (check that it matches the selected environment)"
    if status is not None:
        return False, f"Tremendous returned HTTP {status}"
    return False, "Could not validate Tremendous API key"
