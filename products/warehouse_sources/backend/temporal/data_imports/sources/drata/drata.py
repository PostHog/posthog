import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import (
    DRATA_ENDPOINTS,
    DrataEndpointConfig,
)

# Drata hosts its public API per data-residency region; the user picks their region at connect time.
REGION_BASE_URLS: dict[str, str] = {
    "US": "https://public-api.drata.com/public/v2",
    "EU": "https://public-api.eu.drata.com/public/v2",
    "APAC": "https://public-api.apac.drata.com/public/v2",
}
DEFAULT_REGION = "US"
# Cheap list probe used to confirm an API key is genuine. Any authenticated endpoint works; the
# workspaces list is small on every account.
PROBE_PATH = "/workspaces"
# Query param carrying the page size; the v2 API allows 1-500 (default 50).
PAGE_SIZE_PARAM = "size"
# Cursor jsonpath every v2 list endpoint returns while more pages exist.
CURSOR_PATH = "pagination.cursor"


@dataclasses.dataclass
class DrataResumeConfig:
    # Opaque `pagination.cursor` pointing at the page after the last one yielded on a top-level
    # (non-fan-out) endpoint. A crashed sync resumes from there; merge dedupes the re-pulled page.
    cursor: str | None = None
    # Legacy fan-out bookmark (stable parent id). Kept only so pre-migration saved state still
    # parses via `dataclass(**saved)`; fan-out now checkpoints through `fanout_state`.
    parent_id: int | None = None
    # Framework fan-out resume snapshot: {"completed": [child_path, ...], "current": child_path |
    # None, "child_state": {...} | None}. Present only for fan-out endpoints.
    fanout_state: dict | None = None


def base_url_for_region(region: str | None) -> str:
    return REGION_BASE_URLS.get((region or DEFAULT_REGION).upper(), REGION_BASE_URLS[DEFAULT_REGION])


def _format_incremental_value(value: Any) -> str:
    # Drata's date-time params take ISO 8601; normalize to UTC with a Z suffix to avoid ambiguity.
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_incremental_params(
    config: DrataEndpointConfig,
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
        raise ValueError(f"Drata endpoint '{config.name}' has no server-side filter for field '{field}'")

    return {param: _format_incremental_value(db_incremental_field_last_value)}


class DrataCursorPaginator(BasePaginator):
    """Cursor pagination over Drata v2 ``pagination.cursor``.

    Terminates on an empty page, an absent/empty cursor, or a cursor that stops advancing (some
    endpoints echo the same cursor back), mirroring the hand-rolled walk this replaces. The cursor
    rides in a query param, so it is redaction-safe and needs no off-host guard.
    """

    def __init__(self, cursor_param: str = "cursor") -> None:
        super().__init__()
        self._cursor_param = cursor_param
        # Cursor sent on the request just issued (None on the first page unless resuming).
        self._current_cursor: str | None = None
        # Cursor to send on the next request.
        self._next_cursor: str | None = None

    def _apply(self, request: Request) -> None:
        if self._current_cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self._cursor_param] = self._current_cursor

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values(CURSOR_PATH, response.json())
        except Exception:
            values = []
        next_cursor = values[0] if values else None
        if not data or not next_cursor or next_cursor == self._current_cursor:
            self._has_next_page = False
        else:
            self._next_cursor = next_cursor
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._current_cursor = self._next_cursor
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._next_cursor} if self._has_next_page and self._next_cursor else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._current_cursor = cursor
            self._has_next_page = True


def _client_config(api_key: str, region: str) -> ClientConfig:
    # Framework Bearer auth so the key is redacted from logs and raised error messages; only the
    # non-secret Accept header is set here. A shared cursor paginator applies to every resource
    # (it is deep-copied per pagination run inside the client).
    return {
        "base_url": base_url_for_region(region),
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": DrataCursorPaginator(),
    }


def _base_params(config: DrataEndpointConfig) -> dict[str, Any]:
    # An explicit stable creation-order sort keeps cursor pages consistent while rows are inserted
    # mid-sync.
    return {"sort": config.sort, "sortDir": "ASC", PAGE_SIZE_PARAM: config.page_size}


def _top_level_resource(
    api_key: str,
    region: str,
    config: DrataEndpointConfig,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Any:
    params = _base_params(config)
    params.update(
        _build_incremental_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
    )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, region),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    # A 200 whose body isn't the expected {"data": [...]} shape is transient (a
                    # truncating proxy, an error envelope) — retry rather than fail loud.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes) rather
        # than skipping it; persist only while a next page remains.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(DrataResumeConfig(cursor=state["cursor"]))

    return rest_api_resource(
        rest_config,
        0,
        "",
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_resource(
    api_key: str,
    region: str,
    config: DrataEndpointConfig,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
) -> Any:
    assert config.fan_out_parent is not None and config.fan_out_parent_id_column is not None
    parent_config = DRATA_ENDPOINTS[config.fan_out_parent]
    parent_key = f"_{config.fan_out_parent}_id"
    parent_id_column = config.fan_out_parent_id_column

    def inject_parent_id(row: dict[str, Any]) -> dict[str, Any]:
        # Child rows don't carry their parent id natively; rename the framework's include_from_parent
        # column to the camelCase column the composite ["<parent>Id", "id"] primary key expects.
        if parent_key in row:
            row[parent_id_column] = row.pop(parent_key)
        return row

    child_params: dict[str, Any] = {
        "parent_id": {"type": "resolve", "resource": config.fan_out_parent, "field": "id"},
        **_base_params(config),
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, region),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.fan_out_parent,
                "endpoint": {
                    "path": parent_config.path,
                    "params": _base_params(parent_config),
                    "data_selector": "data",
                },
            },
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": child_params,
                    "data_selector": "data",
                    # A parent deleted between enumeration and this fetch 404s; skip it and continue
                    # rather than failing the whole sync — its children are genuinely gone.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "include_from_parent": ["id"],
                "data_map": inject_parent_id,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(DrataResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        0,
        "",
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def drata_source(
    api_key: str,
    region: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = DRATA_ENDPOINTS[endpoint]

    if config.fan_out_parent:
        resource = _fan_out_resource(api_key, region, config, resumable_source_manager)
    else:
        resource = _top_level_resource(
            api_key,
            region,
            config,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
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
        # Every request passes sort=createdAt&sortDir=ASC, but the ordering couldn't be verified
        # against a live account, so the incremental endpoint declares "desc": the pipeline then
        # commits the watermark only after a complete sync, which stays correct regardless of the
        # actual arrival order.
        sort_mode="desc" if config.incremental_fields else "asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url_for_region(region)}{PROBE_PATH}?{PAGE_SIZE_PARAM}=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Drata API key"
    if status == 403:
        # The key is genuine but lacks the workspaces read scope. Custom-scoped keys may
        # legitimately only grant the endpoints the user wants to sync, so don't block
        # source-create on it; sync-time 403s are surfaced per table.
        return True, None
    if status == 412:
        return False, "You must accept the Drata API terms and conditions in your Drata account before connecting"
    if status is None:
        return False, "Could not connect to Drata"
    return False, f"Drata returned HTTP {status}"
