import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.settings import TELNYX_ENDPOINTS

TELNYX_BASE_URL = "https://api.telnyx.com"
# Detail Record Search caps `page[size]` at 50 (general list endpoints allow up to 250).
PAGE_SIZE = 50


@dataclasses.dataclass
class TelnyxResumeConfig:
    next_page: int


def _format_created_at(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp for `filter[<field>][gte]`.

    Telnyx's docs only show a bare date (`2021-06-22`) in examples; a full timestamp is a
    superset of that format and lets incremental syncs re-run within the same day.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    endpoint = TELNYX_ENDPOINTS[name]
    params: dict[str, Any] = {
        "filter[record_type]": endpoint.record_type,
        "page[size]": PAGE_SIZE,
    }

    use_incremental = should_use_incremental_field and endpoint.incremental_field is not None
    if use_incremental and endpoint.incremental_field is not None:
        params[f"filter[{endpoint.incremental_field}][gte]"] = {
            "type": "incremental",
            "cursor_path": endpoint.incremental_field,
            "initial_value": "1970-01-01T00:00:00Z",
            "convert": _format_created_at,
        }
        # Explicit ascending sort on the same field that's being windowed, so the pipeline's
        # incremental watermark advances in the order rows actually arrive.
        params["sort"] = endpoint.incremental_field
    else:
        # Full refresh: an explicit stable sort still prevents page-boundary skips/duplicates
        # if the API's implicit default ordering shifts as rows are inserted mid-sync.
        params["sort"] = endpoint.partition_key

    return {
        "name": endpoint.name,
        "table_name": endpoint.table_name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if use_incremental
        else "replace",
        "endpoint": {
            "data_selector": "data",
            "data_selector_required": True,
            "path": "/v2/detail_records",
            "params": params,
        },
        "table_format": "delta",
    }


def telnyx_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TelnyxResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": TELNYX_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "paginator": PageNumberPaginator(base_page=1, page_param="page[number]", total_path="meta.total_pages"),
            # Detail records carry customer-defined tags, profile names, call metadata, and billing
            # details the name-based sample scrubbers don't recognise, so keep response bodies out of
            # shared HTTP sample storage. Requests are still metered and logged (with the key redacted).
            "session": make_tracked_session(capture=False, redact_values=(api_key,)),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; Redis TTL handles cleanup once
        # the sync completes. Saving AFTER each yielded batch means a crash re-yields the last
        # page rather than skipping it (the merge dedupes on primary key).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(TelnyxResumeConfig(next_page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> bool:
    probe_params: dict[str, str | int] = {"filter[record_type]": "messaging", "page[size]": 1}
    # capture=False: the probe returns a real detail record (customer content) the name-based
    # scrubbers can't reliably redact, so keep it out of shared HTTP sample storage.
    res = make_tracked_session(redact_values=(api_key,), capture=False).get(
        f"{TELNYX_BASE_URL}/v2/detail_records",
        params=probe_params,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return res.status_code == 200
