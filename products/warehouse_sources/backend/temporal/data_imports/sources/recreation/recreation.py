from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import (
    PAGE_LIMIT,
    RECREATION_ENDPOINTS,
    RESERVATIONS_ENDPOINT,
    RESERVATIONS_FORWARD_DAYS,
    RESERVATIONS_LOOKBACK_DAYS,
    RIDB_BASE_URL,
    NestedRowsConfig,
)

VALIDATION_TIMEOUT_SECONDS = 10


@frozen
class RecreationResumeConfig:
    offset: int | None = None
    # `/reservations` pages by page number instead of offset. A resumed run reuses the saved date
    # window, because a moved window shifts the rows behind each page number.
    page: int | None = None
    date_from: str | None = None
    date_to: str | None = None


@frozen
class ReservationsWindow:
    date_from: date
    date_to: date


def _build_paginator() -> OffsetPaginator:
    # RIDB reports the grand total at METADATA.RESULTS.TOTAL_COUNT, so pagination stops
    # without paying an extra empty-page request; the short-page check is the fallback.
    return OffsetPaginator(limit=PAGE_LIMIT, total_path="METADATA.RESULTS.TOTAL_COUNT")


def _nested_rows(nested: NestedRowsConfig) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    def _explode(row: dict[str, Any]) -> list[dict[str, Any]]:
        parent_id = row.get(nested.parent_id_field)
        return [
            {nested.parent_id_field: parent_id, **item}
            for item in row.get(nested.field) or []
            if isinstance(item, dict)
        ]

    return _explode


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = parse_datetime_value(value)
    return parsed.date() if parsed is not None else None


def _reservations_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resume_config: RecreationResumeConfig | None,
    today: date,
) -> ReservationsWindow:
    if resume_config is not None and resume_config.date_from and resume_config.date_to:
        return ReservationsWindow(
            date_from=date.fromisoformat(resume_config.date_from),
            date_to=date.fromisoformat(resume_config.date_to),
        )
    date_from = today - timedelta(days=RESERVATIONS_LOOKBACK_DAYS)
    if should_use_incremental_field:
        # Restart from the watermark day itself: the filter is day-grained, and merge drops the repeats.
        last_value = _as_date(db_incremental_field_last_value)
        if last_value is not None:
            date_from = last_value
    return ReservationsWindow(date_from=date_from, date_to=today + timedelta(days=RESERVATIONS_FORWARD_DAYS))


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool = False,
    reservations_window: ReservationsWindow | None = None,
) -> EndpointResource:
    config = RECREATION_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}
    data_selector = "RECDATA"
    paginator: BasePaginator = _build_paginator()

    if reservations_window is not None:
        params = {
            "dateFrom": reservations_window.date_from.isoformat(),
            "dateTo": reservations_window.date_to.isoformat(),
            "limit": PAGE_LIMIT,
        }
        data_selector = "data"
        # `page` is the number of pages to skip, so the first page is 0. `total_results` counts rows,
        # not pages, so the paginator stops on the first empty page.
        paginator = PageNumberPaginator(base_page=0, page_param="page")

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": "merge" if should_use_incremental_field else "replace",
        "endpoint": {
            "data_selector": data_selector,
            "path": config.path,
            "params": params,
            "paginator": paginator,
        },
        "table_format": "delta",
    }
    if config.nested is not None:
        resource["data_map"] = _nested_rows(config.nested)
    return resource


def recreation_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecreationResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = RECREATION_ENDPOINTS[endpoint]

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    reservations_window: ReservationsWindow | None = None
    if endpoint == RESERVATIONS_ENDPOINT:
        reservations_window = _reservations_window(
            should_use_incremental_field, db_incremental_field_last_value, resume_config, datetime.now(UTC).date()
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": RIDB_BASE_URL,
            "auth": {
                "type": "api_key",
                "name": "apikey",
                "api_key": api_key,
                "location": "header",
            },
            "headers": {"Accept": "application/json"},
            # The apikey credential rides a custom header, which `requests` would replay to a
            # cross-origin redirect target (unlike `Authorization`) — refuse redirects instead.
            "allow_redirects": False,
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, reservations_window)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume_config is not None:
        initial_paginator_state = {
            key: value
            for key, value in (("offset", resume_config.offset), ("page", resume_config.page))
            if value is not None
        } or None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if not state:
            return
        offset, page = state.get("offset"), state.get("page")
        if offset is not None or page is not None:
            resumable_source_manager.save_state(
                RecreationResumeConfig(
                    offset=int(offset) if offset is not None else None,
                    page=int(page) if page is not None else None,
                    date_from=reservations_window.date_from.isoformat() if reservations_window else None,
                    date_to=reservations_window.date_to.isoformat() if reservations_window else None,
                )
            )

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if endpoint_config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [endpoint_config.partition_key],
        }

    primary_keys = [endpoint_config.primary_key]
    if endpoint_config.nested is not None:
        # Attribute and zone rows are unique only within their parent.
        primary_keys = [endpoint_config.nested.parent_id_field, endpoint_config.primary_key]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=primary_keys,
        **partition_kwargs,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        # `allow_redirects=False` matches the sync path's credential boundary: never replay
        # the apikey header to a redirect target.
        res = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            f"{RIDB_BASE_URL}/activities",
            params={"limit": 1},
            headers={"apikey": api_key, "Accept": "application/json"},
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
        if res.status_code == 200:
            return True, None
        if res.status_code in (401, 403):
            return False, "Invalid RIDB API key. Copy the key from your profile at ridb.recreation.gov and try again."
        return False, f"RIDB API returned an unexpected response (HTTP {res.status_code})"
    except Exception as e:
        return False, str(e)
