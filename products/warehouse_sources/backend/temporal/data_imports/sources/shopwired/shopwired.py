import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import (
    PAGE_SIZE,
    SHOPWIRED_ENDPOINTS,
)

# ShopWired's dedicated API domain; the version segment is mandatory in every path.
SHOPWIRED_BASE_URL = "https://api.ecommerceapi.uk/v1"
# Cheap probe used to confirm an API key/secret pair is genuine. Keys are account-wide, so one
# probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/products/count"


@dataclasses.dataclass
class ShopWiredResumeConfig:
    # Number of rows already yielded — ShopWired paginates with `count`/`offset` query params, so a
    # crashed sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0
    # The `from` created-date filter (UNIX timestamp) the interrupted run was using. Pinned in the
    # resume state so a resumed run keeps the same window — recomputing it from a watermark that
    # advanced mid-run would shift rows under the saved offset.
    from_timestamp: int | None = None


def to_unix_timestamp(value: Any) -> int | None:
    """Convert an incremental watermark (datetime, date, epoch number, or date string) to a UNIX
    timestamp for ShopWired's `from` query param. Naive datetimes are treated as UTC so the result
    doesn't depend on the worker's local timezone."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    if isinstance(value, str) and value.strip():
        try:
            parsed = parser.parse(value)
        except (ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    return None


def shopwired_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShopWiredResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SHOPWIRED_ENDPOINTS[endpoint]

    # Only orders exposes a server-side created-date filter (`from`). The value is pinned into the
    # resume state so a resumed run keeps the same window even if the DB watermark advanced.
    last_value = db_incremental_field_last_value if should_use_incremental_field else None
    from_timestamp = to_unix_timestamp(last_value)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            # Keep the interrupted run's `from` window so the saved offset still points at the same rows.
            from_timestamp = resume.from_timestamp
            initial_paginator_state = {"offset": resume.offset}

    params: dict[str, Any] = {}
    if config.sort_param is not None:
        params["sort"] = config.sort_param
    if from_timestamp is not None:
        # Server-side created-date filter (UNIX timestamp). Assumed inclusive, so the watermark
        # row is re-fetched and deduped by the merge on `id`.
        params["from"] = from_timestamp

    # ShopWired list endpoints paginate with count/offset and return a bare JSON array with no total;
    # the order-statuses endpoint documents no pagination params and returns the full list in one call.
    paginator = (
        OffsetPaginator(limit=PAGE_SIZE, offset_param="offset", limit_param="count", total_path=None)
        if config.paginated
        else SinglePagePaginator()
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHOPWIRED_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Private-app auth is HTTP Basic (API key as username, secret as password); the framework
            # auth redacts the secret from logs and raised error messages.
            "auth": HttpBasicAuth(username=api_key, password=api_secret),
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 body that isn't the expected bare JSON array is treated as transient and
                    # retried, matching the hand-rolled source's defensive non-list handling.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                ShopWiredResumeConfig(offset=int(state["offset"]), from_timestamp=from_timestamp)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint if config.paginated else None,
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
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_secret: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API key/secret pair.

    The API key/secret pair is account-wide, so one probe validates access to every list endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, api_secret)),
        f"{SHOPWIRED_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Accept": "application/json"},
        auth=HttpBasicAuth(username=api_key, password=api_secret),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid ShopWired API key or secret"
    if status is None:
        return False, "Could not connect to ShopWired"
    return False, f"ShopWired returned HTTP {status}"
