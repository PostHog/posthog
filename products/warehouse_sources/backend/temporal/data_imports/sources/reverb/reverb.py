import re
from datetime import UTC, datetime
from typing import Any, Optional

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import REVERB_ENDPOINTS

BASE_URL = "https://api.reverb.com/api"

# Reverb payout objects carry no plain `id` field of their own — the numeric payout id only
# appears embedded in the `_links.line_items.href` URL (e.g. ".../my/payouts/54/line_items").
# Extract it so payouts have a stable primary key to merge on.
_PAYOUT_ID_RE = re.compile(r"/my/payouts/(\d+)/line_items")


@frozen
class ReverbResumeConfig:
    next_page: Optional[int] = None


def _format_datetime(value: Any) -> str:
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    # Never send a window bound in the future — the API has nothing to compare it against yet.
    capped = min(normalized, datetime.now(UTC))
    return capped.strftime("%Y-%m-%dT%H:%M:%SZ")


def _incremental_window(start_param: str, end_param: str, cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": start_param,
        "end_param": end_param,
        "initial_value": "1970-01-01T00:00:00Z",
        "end_value": _format_datetime(datetime.now(UTC)),
        "convert": _format_datetime,
    }


def _inject_payout_id(row: dict[str, Any]) -> dict[str, Any]:
    href = ((row.get("_links") or {}).get("line_items") or {}).get("href") or ""
    match = _PAYOUT_ID_RE.search(href)
    if match:
        row["id"] = int(match.group(1))
    return row


class ReverbPageNumberPaginator(PageNumberPaginator):
    """Page-number pagination using Reverb's `total_pages` metadata, with a full-page fallback.

    Reverb reports `total_pages` on every collection response, which the base paginator uses to
    stop after the last page. If that metadata is ever absent, fall back to the full-page
    heuristic: a short page means there are no more pages.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page", total_path="total_pages")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page or data is None:
            return
        try:
            values = find_values(self.total_path, response.json()) if self.total_path else []
        except Exception:
            values = []
        has_total_metadata = bool(values) and isinstance(values[0], int)
        if not has_total_metadata and len(data) < self._page_size:
            self._has_next_page = False


def _client_config(api_token: str, page_size: int, api_version: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        # Auth (Bearer) goes through the framework auth config so its value is redacted from
        # logs; only non-secret headers are set here. Accept-Version is required — Reverb
        # rejects requests without it.
        "headers": {
            "Accept": "application/hal+json",
            "Content-Type": "application/hal+json",
            "Accept-Version": api_version,
        },
        "auth": {"type": "bearer", "token": api_token},
        "paginator": ReverbPageNumberPaginator(page_size=page_size),
    }


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = REVERB_ENDPOINTS[name]
    params: dict[str, Any] = {"per_page": config.page_size}

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.response_key,
    }

    use_incremental = (
        should_use_incremental_field
        and config.incremental_start_param is not None
        and config.incremental_end_param is not None
    )
    if use_incremental:
        assert config.incremental_start_param is not None
        assert config.incremental_end_param is not None
        endpoint_config["incremental"] = _incremental_window(
            config.incremental_start_param,
            config.incremental_end_param,
            config.default_incremental_field or "id",
        )

    return {
        "name": name,
        "table_name": name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def reverb_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ReverbResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    api_version: str,
) -> SourceResponse:
    config = REVERB_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token, config.page_size, api_version),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ReverbResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    if endpoint == "Payouts":
        resource = resource.add_map(_inject_payout_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str, api_version: str) -> tuple[bool, int | None]:
    """Probe Reverb's `/my/account` endpoint to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{BASE_URL}/my/account",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/hal+json",
            "Content-Type": "application/hal+json",
            "Accept-Version": api_version,
        },
    )
