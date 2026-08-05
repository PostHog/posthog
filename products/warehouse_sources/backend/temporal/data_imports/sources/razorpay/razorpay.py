import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import (
    API_BASE_URL,
    ENDPOINT_CONFIGS,
    PAGE_SIZE,
)

# Razorpay has no updated-at filter, so incremental syncs window on created_at only. Re-read a
# trailing overlap each run to catch status transitions on recently created records (e.g.
# authorized -> captured payments, settlement state changes); the merge on `id` dedupes the
# overlap. Older mutations still need an occasional full refresh.
INCREMENTAL_LOOKBACK_SECONDS = 3 * 24 * 60 * 60

# The API rejects `from` values before 2000-01-01 with a 400.
MIN_FROM_TIMESTAMP = 946_684_800


@dataclasses.dataclass
class RazorpayResumeConfig:
    skip: int


def build_from_param(db_incremental_field_last_value: Optional[Any]) -> Optional[int]:
    """UNIX-seconds `from` bound for an incremental sync, or None for a full walk."""
    if db_incremental_field_last_value is None:
        return None

    try:
        watermark = int(db_incremental_field_last_value)
    except (TypeError, ValueError):
        return None

    return max(watermark - INCREMENTAL_LOOKBACK_SECONDS, MIN_FROM_TIMESTAMP)


def _build_paginator() -> OffsetPaginator:
    # Collection responses carry `count` as the page's item count (not a grand total), so
    # termination is a short or empty page; `total_path=None` keeps the paginator from
    # misreading any body field as a total.
    return OffsetPaginator(
        limit=PAGE_SIZE,
        offset_param="skip",
        limit_param="count",
        total_path=None,
    )


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    config = ENDPOINT_CONFIGS[name]

    params: dict[str, Any] = {}
    if config.supports_created_filter and should_use_incremental_field:
        # None values are dropped before the request, so the first incremental sync (no
        # watermark yet) walks the full history without a `from` bound.
        params["from"] = build_from_param(db_incremental_field_last_value)

    return {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "items",
            "path": config.path,
            "params": params,
            "paginator": _build_paginator(),
        },
        "table_format": "delta",
    }


def razorpay_source(
    key_id: str,
    key_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RazorpayResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> Resource:
    config: RESTAPIConfig = {
        "client": {
            "base_url": API_BASE_URL,
            "auth": {
                "type": "http_basic",
                "username": key_id,
                "password": key_secret,
            },
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value if should_use_incremental_field else None,
            )
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(RazorpayResumeConfig(skip=int(state["offset"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(key_id: str, key_secret: str) -> bool:
    session = make_tracked_session(redact_values=(key_secret,))
    res = session.get(
        f"{API_BASE_URL}/v1/payments",
        params={"count": 1},
        auth=(key_id, key_secret),
        timeout=30,
    )
    return res.status_code == 200
