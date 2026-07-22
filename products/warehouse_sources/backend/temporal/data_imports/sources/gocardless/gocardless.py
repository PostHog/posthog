import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import GOCARDLESS_ENDPOINTS

GOCARDLESS_HOSTS = {
    "live": "https://api.gocardless.com",
    "sandbox": "https://api-sandbox.gocardless.com",
}
# Every request must pin an API version via this header.
GOCARDLESS_VERSION = "2015-07-06"
# GoCardless list pages cap at 500 items.
PAGE_SIZE = 500


@dataclasses.dataclass
class GoCardlessResumeConfig:
    # GoCardless cursor pagination: `after=<id>` from meta.cursors.after; the
    # static params are deterministically rebuilt from job inputs on resume.
    after: str


class GoCardlessCursorPaginator(JSONResponseCursorPaginator):
    """GoCardless cursor pagination via ``meta.cursors.after`` (``after=<id>``).

    Also stops on an empty page even when the response still carries an ``after``
    cursor, so a run can never loop on a stale cursor that points at no rows.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="meta.cursors.after", cursor_param="after")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def _base_url(environment: str) -> str:
    host = GOCARDLESS_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid GoCardless environment: {environment}")
    return host


def _format_created_at(value: Any) -> str:
    """Format an incremental cursor for GoCardless's created_at filters (ISO 8601 UTC with ms)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def validate_credentials(environment: str, access_token: str) -> bool:
    """Confirm the access token is valid with a cheap one-customer probe."""
    try:
        base_url = _base_url(environment)
    except ValueError:
        return False

    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{base_url}/customers?{urlencode({'limit': 1})}",
        headers={"Authorization": f"Bearer {access_token}", "GoCardless-Version": GOCARDLESS_VERSION},
    )
    return ok


def gocardless_source(
    environment: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GoCardlessResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GOCARDLESS_ENDPOINTS[endpoint]
    base_url = _base_url(environment)

    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if config.incremental_fields and db_incremental_field_last_value is not None:
        # `gte` re-fetches the boundary row (merge dedupes on primary key) so
        # records sharing the watermark timestamp are never skipped.
        params["created_at[gte]"] = _format_created_at(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted
            # from logs and raised errors; only the non-secret version header is set here.
            "headers": {"GoCardless-Version": GOCARDLESS_VERSION},
            "auth": {"type": "bearer", "token": access_token},
            "paginator": GoCardlessCursorPaginator(),
            # Cursor pagination stays on the base host; pin every request (including a seeded
            # resume cursor) to it so a spoofed response can't redirect the token off-host.
            "allowed_hosts": [],
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # GoCardless wraps rows under a per-resource key; a missing key is treated
                    # as an empty page (not fail-loud), matching the hand-rolled behavior.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(GoCardlessResumeConfig(after=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        # GoCardless lists are reverse-chronological with no sort param; the
        # pipeline commits desc-sort watermarks only when a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
        column_hints=resource.column_hints,
    )
