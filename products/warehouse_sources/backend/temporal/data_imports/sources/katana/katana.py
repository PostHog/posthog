import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.settings import KATANA_ENDPOINTS

KATANA_BASE_URL = "https://api.katanamrp.com/v1"
# Katana caps list pages at 250 rows; use the max to minimise request count against the 60 req/min limit.
PAGE_SIZE = 250


@dataclasses.dataclass
class KatanaResumeConfig:
    # Page to fetch on resume. Katana paginates by page number and exposes no next-page cursor, so a
    # restart re-issues from this page; the delta merge dedupes any overlap with already-written rows.
    page: int = 1


class KatanaPaginator(PageNumberPaginator):
    """Page-number pagination where a SHORT page (fewer rows than the requested limit) is the last page.

    Katana exposes no next-page cursor, so any page below ``PAGE_SIZE`` ends the sync (this also covers
    the empty-page case). Resume (the page number) is inherited from ``PageNumberPaginator``.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1)
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and (data is None or len(data) < self._page_size):
            self._has_next_page = False


def _format_datetime_z(dt: datetime) -> str:
    """ISO 8601 with millisecond precision and a Z suffix (Katana filters expect ISO 8601)."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future cursor at now so we never send a future `<field>_min` filter (a no-op that could
    otherwise wedge the sync if the source has future-dated rows)."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _incremental_filter_value(value: Any) -> Any:
    """Framework ``convert`` hook for the ``<field>_min`` param: clamp a future cursor to now, then
    format ISO 8601. Returns ``None`` when there's no cursor (first sync) so the param is dropped and
    no server-side filter is sent."""
    if not value:
        return None
    return _format_incremental_value(_clamp_future_value_to_now(value))


def validate_credentials(api_key: str) -> bool:
    """Cheap token probe: `/user_info` returns 200 for a valid key regardless of resource scopes."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{KATANA_BASE_URL}/user_info",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=15,
    )
    return ok


def katana_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KatanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = KATANA_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if should_use_incremental_field and config.incremental_fields:
        field_name = incremental_field or config.default_incremental_field
        # Server-side timestamp filter. The framework injects this on every page and drops it when the
        # cursor is empty (first sync), reproducing the original `<field>_min` behaviour.
        params[f"{field_name}_min"] = {
            "type": "incremental",
            "cursor_path": field_name,
            "convert": _incremental_filter_value,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": KATANA_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so the key is redacted from logs and
            # raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": KatanaPaginator(PAGE_SIZE),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    # Every Katana list endpoint wraps results as {"data": [...]}. A 2xx body missing the
                    # `data` list (maintenance page, changed envelope) would otherwise read as an empty
                    # page and silently end the sync mid-run, so treat it as retryable rather than lose
                    # data.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework saves AFTER a page is yielded, so a crash
        # re-issues the saved page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(KatanaResumeConfig(page=int(state["page"])))

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
        # Katana list endpoints always return newest-first by created_at and expose no sort override,
        # so rows arrive descending. The pipeline finalises the incremental watermark (max cursor) only
        # at the end for desc sources, which keeps it correct despite the fixed order.
        sort_mode="desc",
        column_hints=resource.column_hints,
    )
