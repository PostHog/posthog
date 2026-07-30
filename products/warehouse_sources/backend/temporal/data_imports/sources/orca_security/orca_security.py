import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import (
    DEFAULT_REGION,
    ORCA_ENDPOINTS,
    ORCA_REGION_HOSTS,
    PAGE_SIZE,
    QUERY_PATH,
    OrcaEndpointConfig,
)


@dataclasses.dataclass
class OrcaResumeConfig:
    # Serving Layer offset (`start_at_index`) of the next page to fetch. Offset pagination has no
    # opaque cursor, so the offset alone is enough to pick back up after a heartbeat timeout.
    start_at_index: int = 0


def _host(region: str) -> str:
    return ORCA_REGION_HOSTS.get(region or DEFAULT_REGION, ORCA_REGION_HOSTS[DEFAULT_REGION])


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an ISO 8601 string. Orca's Serving Layer is strict about the format."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_query_body(
    config: OrcaEndpointConfig,
    incremental_field: str | None,
    formatted_last_value: str | None,
) -> dict[str, Any]:
    """Build the static Serving Layer object_set request body for a stream (minus ``start_at_index``,
    which the paginator injects per page)."""
    query: dict[str, Any] = {"models": [config.model], "type": "object_set"}

    # Server-side incremental filter, only for streams with a verified `date_gte`-able field.
    if config.incremental_key and formatted_last_value:
        filter_field = incremental_field or config.incremental_key
        query["with"] = {
            "type": "operation",
            "operator": "and",
            "values": [
                {
                    "key": filter_field,
                    "values": [formatted_last_value],
                    "type": "datetime",
                    "operator": "date_gte",
                    "value_type": "days",
                }
            ],
        }

    body: dict[str, Any] = {"query": query, "limit": PAGE_SIZE}
    # Ascending order on the incremental field keeps the pipeline's watermark advancing correctly
    # (matches SourceResponse.sort_mode="asc") and gives offset pagination a stable order.
    if config.incremental_key:
        body["order_by[]"] = [config.incremental_key]

    return body


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Serving Layer object into a flat row.

    Objects arrive as ``{"id", "type", "data": {"Field": {"value": ...}}}``. We lift the stable
    top-level ``id``/``type`` and unwrap each ``{"value": ...}`` field to the row root so the
    warehouse table has queryable columns instead of a single nested blob.
    """
    row: dict[str, Any] = {}
    if "id" in item:
        row["id"] = item["id"]
    if "type" in item:
        row["type"] = item["type"]

    data = item.get("data")
    if isinstance(data, dict):
        for key, wrapped in data.items():
            if isinstance(wrapped, dict) and "value" in wrapped:
                row[key] = wrapped["value"]
            else:
                row[key] = wrapped
    return row


class OrcaOffsetPaginator(BasePaginator):
    """Serving Layer offset pagination carried in the POST body.

    Orca returns rows under ``data`` and an optional ``next_page_token`` (the next offset). We honor
    that token when present and otherwise advance ``start_at_index`` by the number of rows returned;
    a short page (fewer than ``PAGE_SIZE`` rows with no token) or an empty page ends the stream.
    """

    def __init__(self, page_size: int, start_at_index: int = 0) -> None:
        super().__init__()
        self.page_size = page_size
        self.start_at_index = start_at_index

    def _inject_offset(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["start_at_index"] = self.start_at_index

    def init_request(self, request: Request) -> None:
        self._inject_offset(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if not items:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}
        next_token = body.get("next_page_token") if isinstance(body, dict) else None

        # A short page with no continuation token means we've reached the end.
        if not next_token and len(items) < self.page_size:
            self._has_next_page = False
            return

        self.start_at_index = int(next_token) if next_token else self.start_at_index + len(items)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_offset(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.start_at_index already points at the next page (update_state advanced it).
        return {"start_at_index": self.start_at_index} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        start_at_index = state.get("start_at_index")
        if start_at_index is not None:
            self.start_at_index = int(start_at_index)
            self._has_next_page = True


def orca_source(
    api_token: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OrcaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ORCA_ENDPOINTS[endpoint]

    formatted_last_value = (
        _format_datetime(db_incremental_field_last_value)
        if should_use_incremental_field and config.incremental_key and db_incremental_field_last_value
        else None
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _host(region),
            # Only non-secret headers here; the token rides on framework auth so it's redacted.
            "headers": {"Content-Type": "application/json", "Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": f"Token {api_token}", "name": "Authorization", "location": "header"},
            "paginator": OrcaOffsetPaginator(page_size=PAGE_SIZE),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": QUERY_PATH,
                    "method": "post",
                    "json": _build_query_body(config, incremental_field, formatted_last_value),
                    "data_selector": "data",
                },
                # Lift id/type and unwrap `{"value": ...}` fields into a flat row.
                "data_map": _normalize_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"start_at_index": resume.start_at_index}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("start_at_index") is not None:
            resumable_source_manager.save_state(OrcaResumeConfig(start_at_index=int(state["start_at_index"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental is applied server-side via the request body above, not framework params.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str, region: str) -> tuple[bool, Optional[str]]:
    """Probe the token against a cheap single-row Serving Layer query (POST-only endpoint)."""
    url = f"{_host(region)}{QUERY_PATH}"
    payload = {"query": {"models": ["CloudAccount"], "type": "object_set"}, "limit": 1, "start_at_index": 0}
    try:
        response = make_tracked_session(redact_values=(api_token,)).post(
            url, headers=_headers(api_token), json=payload, timeout=30
        )
    except Exception as e:
        return False, f"Could not reach Orca Security ({e}). Check your network and the selected region, then retry."

    if response.status_code in (401, 403):
        return (
            False,
            "Orca rejected the API token. Generate a new token in Settings → Users & Permissions → API and reconnect.",
        )
    if not response.ok:
        return False, f"Orca API returned an unexpected status ({response.status_code}). Please retry."
    return True, None
