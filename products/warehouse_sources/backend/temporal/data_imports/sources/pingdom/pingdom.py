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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    PINGDOM_ENDPOINTS,
    PingdomEndpointConfig,
)

PINGDOM_BASE_URL = "https://api.pingdom.com/api/3.1"


@dataclasses.dataclass
class PingdomResumeConfig:
    # Pingdom paginates with limit/offset; the static query params (limit,
    # incremental `from` filter) are deterministically rebuilt from the endpoint
    # config and job inputs on resume.
    offset: int = 0


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch seconds for Pingdom's `from` filter."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_endpoint(config: PingdomEndpointConfig, should_use_incremental_field: bool) -> Endpoint:
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    params: dict[str, Any] = {}
    if is_incremental:
        cursor = config.incremental_fields[0]["field"]
        # Pingdom's `from` filter takes UNIX epoch seconds; only /actions exposes it.
        params["from"] = {
            "type": "incremental",
            "cursor_path": cursor,
            "initial_value": None,
            "convert": _to_epoch,
        }

    return {
        "path": config.path,
        "params": params,
        # Dotted selector (e.g. "actions.alerts") resolves the nested list; a 200 body that
        # lacks the key yields zero rows and stops (no data_selector_required — Pingdom's small
        # dimension endpoints legitimately return an empty/absent list).
        "data_selector": config.data_key,
        "paginator": OffsetPaginator(limit=config.page_size, total_path=None),
    }


def pingdom_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PingdomResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = PINGDOM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PINGDOM_BASE_URL,
            # Bearer auth via the framework so the token is redacted from logs and error messages.
            "auth": {"type": "bearer", "token": api_token},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint(config, should_use_incremental_field),
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
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(PingdomResumeConfig(offset=int(state["offset"])))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        has_duplicate_primary_keys=config.has_duplicate_primary_keys or None,
    )


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with a cheap one-check listing probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{PINGDOM_BASE_URL}/checks?limit=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return ok
