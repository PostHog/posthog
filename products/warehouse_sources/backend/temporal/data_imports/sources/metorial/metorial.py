import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import METORIAL_ENDPOINTS

METORIAL_BASE_URL = "https://api.metorial.com"
# Pin the API version so response shapes don't shift under us when Metorial changes an environment's
# default version. See https://metorial.com/api ("Versioning").
METORIAL_API_VERSION = "2025-01-01"
# Default page size. Metorial doesn't document a max, so stay conservatively within a value cursor
# APIs commonly accept while keeping request counts down against the tight per-key rate limit.
DEFAULT_PAGE_SIZE = 100


@dataclasses.dataclass
class MetorialResumeConfig:
    # Cursor (a record id) to fetch the next page from. None means "start at the first page".
    after: str | None = None


def _version_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised error messages; only the non-secret version/accept headers are set here.
    return {"Metorial-Version": METORIAL_API_VERSION, "Accept": "application/json"}


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with a millisecond precision and a Z suffix (Metorial's format)."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _incremental_filter_value(value: Any) -> Any:
    """Framework ``convert`` hook for the ``<field>[gt]`` param. Returns ``None`` when there's no
    cursor (first sync) so the param is dropped and no server-side filter is sent."""
    if not value:
        return None
    return _format_incremental_value(value)


class MetorialCursorPaginator(BasePaginator):
    """Metorial paginates by an ``after`` cursor set to the last row's ``id``, terminating when the
    body's ``pagination.has_more_after`` is false (or a page comes back empty). No built-in paginator
    matches: the cursor is derived from the row data (not a body field) and termination is a separate
    boolean flag. Resume persists the ``after`` cursor.
    """

    def __init__(self, cursor_param: str = "after") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._after: str | None = None

    def _apply_cursor(self, request: Request) -> None:
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._after

    def init_request(self, request: Request) -> None:
        # Seed a resumed cursor onto the first request so a restart continues mid-stream.
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            pagination = response.json().get("pagination", {})
        except Exception:
            pagination = {}
        if not data or not pagination.get("has_more_after", False):
            self._has_next_page = False
            self._after = None
        else:
            self._after = data[-1]["id"]
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"after": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._after = after
            self._has_next_page = True

    def __str__(self) -> str:
        return f"MetorialCursorPaginator(after={self._after})"


def _make_drop_map(drop_fields: list[str]) -> Any:
    def _drop(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key not in drop_fields}

    return _drop


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe: list one session. 200 => the secret key is genuine and project-scoped.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{METORIAL_BASE_URL}/sessions?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_version_headers()},
    )
    return ok


def metorial_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MetorialResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = METORIAL_ENDPOINTS[endpoint]

    # `order=asc` paginates deterministically by record id. The incremental filter is re-sent on every
    # page so pagination can never walk back past the watermark. Note this orders by id, not by the
    # incremental field: `created_at` tracks id order (safe to checkpoint per batch), but `updated_at`
    # does not, so `updated_at` syncs run in `sort_mode="desc"` (see below).
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE, "order": "asc"}

    if should_use_incremental_field and config.incremental_fields:
        field_name = incremental_field or config.default_incremental_field
        # Metorial documents these as `created_at`/`updated_at` objects with `.gt`/`.lt` operators.
        # Bracket notation is the standard query-string encoding for such nested filter objects. The
        # framework injects this on every page and drops it when the cursor is empty (first sync).
        params[f"{field_name}[gt]"] = {
            "type": "incremental",
            "cursor_path": field_name,
            "convert": _incremental_filter_value,
        }

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            # A 200 body without `items` reads as an empty page and stops the sync, matching the
            # original `data.get("items", [])` behaviour (never fail loud on a missing key).
            "data_selector": "items",
        },
    }
    if config.drop_fields:
        # Strip sensitive fields (e.g. a live client_secret) from every row before it lands.
        resource_config["data_map"] = _make_drop_map(config.drop_fields)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": METORIAL_BASE_URL,
            "headers": _version_headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": MetorialCursorPaginator(),
        },
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.after is not None:
            initial_paginator_state = {"after": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("after") is not None:
            resumable_source_manager.save_state(MetorialResumeConfig(after=state["after"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    # Pagination is `order=asc` by record id. Metorial ids are time-sorted, so a `created_at` sync
    # genuinely arrives oldest-first and the pipeline can safely checkpoint the watermark after each
    # batch. `updated_at` is NOT monotonic in id order (a row created long ago can be updated
    # recently), so those syncs run `desc`: the pipeline then commits the watermark only after a full
    # successful run, so an interrupted sync can't advance past rows it hasn't fetched yet.
    chosen_field = incremental_field or config.default_incremental_field
    sort_mode: SortMode = "asc" if chosen_field in (None, "created_at") else "desc"

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )
