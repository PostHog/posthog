import base64
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.close.settings import (
    CLOSE_ENDPOINTS,
    CloseEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLOSE_BASE_URL = "https://api.close.com/api/v1"
PAGE_LIMIT = 100
# Far-past cutoff used on the first incremental sync (no stored watermark yet) so we
# pull the full history before the cursor takes over on subsequent runs.
INITIAL_INCREMENTAL_VALUE = "1970-01-01T00:00:00+00:00"


@dataclasses.dataclass
class CloseResumeConfig:
    next_skip: int


def _format_close_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Close expects for `<field>__gte`."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        try:
            dt = parser.parse(str(value))
        except (ValueError, OverflowError):
            return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


class CloseOffsetPaginator(OffsetPaginator):
    """Offset paginator driven by Close's `has_more` response flag.

    Close list endpoints page with `_skip`/`_limit` and return `{"data": [...], "has_more": bool}`.
    Small dimension endpoints omit `has_more`; treating a missing flag as `False` stops after the
    single page they return.
    """

    def __init__(self, limit: int = PAGE_LIMIT, offset: int = 0) -> None:
        super().__init__(
            limit=limit,
            offset=offset,
            offset_param="_skip",
            limit_param="_limit",
            total_path=None,
            stop_after_empty_page=True,
        )

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        try:
            body = response.json()
            has_more = bool(body.get("has_more")) if isinstance(body, dict) else False
        except (ValueError, AttributeError):
            has_more = False

        if not has_more:
            self._has_next_page = False
            return

        self.offset += self.limit
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"skip": self.offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        skip = state.get("skip")
        if skip is not None:
            self.offset = int(skip)
            self._has_next_page = True


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> EndpointResource:
    config: CloseEndpointConfig = CLOSE_ENDPOINTS[endpoint]

    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    params: dict[str, Any] = {}
    if is_incremental:
        # Honor the user's chosen cursor field; fall back to the first advertised option.
        advertised = {f["field"] for f in config.incremental_fields}
        cursor = incremental_field if incremental_field in advertised else config.incremental_fields[0]["field"]
        params[f"{cursor}__gte"] = {
            "type": "incremental",
            "cursor_path": cursor,
            "initial_value": INITIAL_INCREMENTAL_VALUE,
            "convert": _format_close_datetime,
        }
        if config.supports_order_by:
            # Ascending sort on the cursor so the pipeline watermark advances correctly
            # (matches SourceResponse.sort_mode="asc").
            params["_order_by"] = cursor

    endpoint_def: Endpoint = {
        "data_selector": config.data_selector,
        "path": config.path,
        "params": params,
    }
    # Dimension endpoints that take no `_skip`/`_limit` get a single-page paginator so we don't
    # inject pagination params the API doesn't accept; everything else uses the client default.
    if not config.paginated:
        endpoint_def["paginator"] = SinglePagePaginator()

    return {
        "name": config.name,
        "table_name": config.table_name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint_def,
        "table_format": "delta",
    }


def close_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloseResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": {
            "base_url": CLOSE_BASE_URL,
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
            "paginator": CloseOffsetPaginator(),
        },
        # Write disposition is set per-resource in get_resource (it always wins over
        # resource_defaults), so no default is needed here.
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"skip": resume_config.next_skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to. Redis TTL handles cleanup on completion.
        if state and state.get("skip") is not None:
            resumable_source_manager.save_state(CloseResumeConfig(next_skip=int(state["skip"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    endpoint_config = CLOSE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    try:
        response = make_tracked_session().get(
            f"{CLOSE_BASE_URL}/me/",
            headers={"Authorization": f"Basic {basic_token}"},
            timeout=30,
        )
    except Exception:
        return False
    return response.status_code == 200
