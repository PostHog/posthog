import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    CAL_COM_ENDPOINTS,
    CalComEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CAL_COM_BASE_URL = "https://api.cal.com/v2"
# Cheap single-object endpoint used to confirm an API key is genuine. The key is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/me"


@dataclasses.dataclass
class CalComResumeConfig:
    # Opaque `pagination.nextCursor` for cursor-paginated endpoints (bookings). A crashed sync
    # resumes from the page after the last one yielded; merge dedupes the re-pulled page on `id`.
    cursor: str | None = None
    # `skip` offset for offset-paginated endpoints (webhooks).
    skip: int | None = None


def _headers(config: CalComEndpointConfig) -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret headers are set here. Cal.com versions endpoints individually via the
    # `cal-api-version` header; omitting it silently falls back to a legacy behavior, so it must be
    # pinned per endpoint.
    headers = {"Accept": "application/json"}
    if config.api_version:
        headers["cal-api-version"] = config.api_version
    return headers


def _format_incremental_value(value: Any) -> str:
    # Cal.com's afterUpdatedAt/afterCreatedAt filters take ISO 8601 date strings; normalize to UTC
    # with a Z suffix to avoid timezone ambiguity.
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_incremental_params(
    config: CalComEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, str]:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return {}

    field = incremental_field or config.default_incremental_field
    if field is None:
        return {}

    param = config.incremental_param_by_field.get(field)
    if param is None:
        raise ValueError(f"Cal.com endpoint '{config.name}' has no server-side filter for field '{field}'")

    return {param: _format_incremental_value(db_incremental_field_last_value)}


def _make_paginator(config: CalComEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        # Bookings pages carry {"pagination": {"nextCursor": ..., "hasMore": ...}}; a null/absent
        # nextCursor (always the case when hasMore is false) terminates.
        return JSONResponseCursorPaginator(cursor_path="pagination.nextCursor", cursor_param="cursor")
    if config.pagination == "offset":
        # These endpoints return no pagination metadata; a short (or empty) page means we're done.
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="skip",
            limit_param="take",
            total_path=None,
        )
    return SinglePagePaginator()


def cal_com_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CAL_COM_ENDPOINTS[endpoint]

    params: dict[str, Any] = _build_incremental_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    if config.pagination == "cursor":
        # Bookings `limit` maxes at 100; a larger value is rejected with 400 Bad Request. The
        # offset paginator injects its own `take`/`skip` pair.
        params["limit"] = config.page_size

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CAL_COM_BASE_URL,
            "headers": _headers(config),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _make_paginator(config),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Every v2 endpoint wraps its payload as {"status": "success", "data": ...}.
                    # A 200 body without `data` means the response shape changed — fail loud
                    # instead of silently syncing 0 rows.
                    "data_selector": "data",
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "cursor" and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}
            elif config.pagination == "offset" and resume.skip is not None:
                initial_paginator_state = {"offset": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework checkpoints AFTER a page is yielded
        # so a crash re-fetches from the next page (already-yielded pages are persisted) and merge
        # dedupes the re-pulled page on the primary key.
        if not state:
            return
        if config.pagination == "cursor" and state.get("cursor") is not None:
            resumable_source_manager.save_state(CalComResumeConfig(cursor=state["cursor"]))
        elif config.pagination == "offset" and state.get("offset") is not None:
            resumable_source_manager.save_state(CalComResumeConfig(skip=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if config.pagination in ("cursor", "offset") else None,
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
        # Bookings walk `Booking.uuid DESC` (newest-created first) when no status filter is passed,
        # and the opaque cursor doesn't honor sortUpdatedAt/sortCreated. "desc" makes the pipeline
        # commit the incremental watermark only after a complete sync, which stays correct
        # regardless of arrival order.
        sort_mode="desc" if config.incremental_fields else "asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # The API key is account-wide, so a single probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CAL_COM_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Cal.com API key"
    if status is None:
        return False, "Could not connect to Cal.com"
    return False, f"Cal.com returned HTTP {status}"
