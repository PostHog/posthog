import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

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
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.settings import LEMLIST_ENDPOINTS

LEMLIST_BASE_URL = "https://api.lemlist.com/api"
# lemlist caps list pages at 100 rows and rate-limits to 20 requests / 2s per API key.
PAGE_SIZE = 100


@dataclasses.dataclass
class LemlistResumeConfig:
    # Offset of the next page to fetch. lemlist uses limit/offset pagination, so a single integer
    # is enough to pick back up where a crashed run left off.
    offset: int = 0


def _format_datetime_z(value: datetime) -> str:
    """ISO 8601 with a Z suffix — one of the two formats lemlist accepts for minDate/maxDate."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future cursor at now.

    The watermark tracks the max createdAt seen. A future-dated activity would otherwise push the
    cursor past now, and every later sync would ask for activities newer than the future — a no-op
    that just risks tripping lemlist's "maxDate must be greater than minDate" style validation.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def lemlist_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LemlistResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LEMLIST_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.requires_version_v2:
        params["version"] = "v2"
    if config.request_sort_by:
        params["sortBy"] = config.request_sort_by
    if config.request_sort_order:
        params["sortOrder"] = config.request_sort_order

    # lemlist has no top-level `total`; the OffsetPaginator terminates on a short/empty page.
    # Non-paginated endpoints (team, team/senders) return their whole result in one response.
    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "params": params,
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None) if config.paginate else SinglePagePaginator(),
    }

    use_incremental = config.supports_incremental and should_use_incremental_field
    if use_incremental:
        # Only /activities honours the server-side minDate filter. Without a stored watermark yet,
        # bound the first sync by the configured lookback rather than pulling the whole history.
        initial_value: Optional[datetime] = None
        if config.default_lookback_days:
            initial_value = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        endpoint_config["incremental"] = {
            "start_param": "minDate",
            "cursor_path": "createdAt",
            "initial_value": initial_value,
            # Clamp a future watermark to now and render it in the Z-suffixed format lemlist expects.
            "convert": lambda value: _format_incremental_value(_clamp_future_value_to_now(value)),
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": LEMLIST_BASE_URL,
            # lemlist uses HTTP Basic auth with an empty username and the API key as the password.
            # Supplied via the framework auth config so the key is redacted from logs and errors.
            "auth": {"type": "http_basic", "username": "", "password": api_key},
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginate and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(LemlistResumeConfig(offset=int(state["offset"])))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def validate_credentials(api_key: str) -> bool:
    # `/team` is the cheapest authenticated probe — no pagination, single object.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{LEMLIST_BASE_URL}/team",
        auth=HttpBasicAuth(username="", password=api_key),
    )
    return ok
