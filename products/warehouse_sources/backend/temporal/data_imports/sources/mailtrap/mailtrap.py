import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.settings import (
    MAILTRAP_ENDPOINTS,
    MailtrapEndpointConfig,
)

# Management/logs host. Sending hosts (send.api.mailtrap.io, bulk.api.mailtrap.io) are write-only
# and never used by this connector.
MAILTRAP_BASE_URL = "https://mailtrap.io"
# Cheap probe to confirm a token is genuine: every token can list the accounts it has access to.
DEFAULT_PROBE_PATH = "/api/accounts"


@dataclasses.dataclass
class MailtrapResumeConfig:
    # Opaque cursor for the next page: `next_page_cursor` for email_logs, the last suppression's
    # UUID for suppressions. A crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on the primary key. `None` means start from the first page.
    cursor: str | None = None


def _headers() -> dict[str, str]:
    # Only the non-secret Accept header; the Api-Token is supplied via the framework api_key auth
    # so its value is redacted from logs and raised error messages.
    return {"Accept": "application/json"}


def _format_timestamp(value: Any) -> Any:
    # None passes through so the server-side lower bound is dropped (requests skips None params)
    # on a first incremental sync with no watermark yet.
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


class LastIdPaginator(BasePaginator):
    """Cursor pagination keyed off the last row's id (Mailtrap suppressions `last_id`).

    The API exposes no explicit next-page signal, so a full page implies there may be more rows
    after the last id; a short (or empty) page ends the sync. Resumable: the last emitted id is
    persisted so a restart re-fetches only from the page after the last yielded one.
    """

    def __init__(self, id_field: str, cursor_param: str, page_size: Optional[int]) -> None:
        super().__init__()
        self.id_field = id_field
        self.cursor_param = cursor_param
        self.page_size = page_size
        self._last_id: Optional[str] = None

    def _inject(self, request: Request) -> None:
        if self._last_id is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._last_id

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data or (self.page_size is not None and len(data) < self.page_size):
            self._has_next_page = False
            return
        last = data[-1].get(self.id_field)
        if last is None:
            self._has_next_page = False
            return
        self._last_id = str(last)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"last_id": self._last_id} if self._has_next_page and self._last_id is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        last_id = state.get("last_id")
        if last_id is not None:
            self._last_id = str(last_id)
            self._has_next_page = True


def _build_paginator(config: MailtrapEndpointConfig) -> BasePaginator:
    if config.cursor_response_key is not None and config.cursor_param is not None:
        return JSONResponseCursorPaginator(cursor_path=config.cursor_response_key, cursor_param=config.cursor_param)
    if config.cursor_row_field is not None and config.cursor_param is not None:
        return LastIdPaginator(
            id_field=config.cursor_row_field, cursor_param=config.cursor_param, page_size=config.page_size
        )
    return SinglePagePaginator()


def _initial_paginator_state(config: MailtrapEndpointConfig, cursor: str) -> dict[str, Any]:
    # Seed the resume cursor under the key the endpoint's paginator reads.
    if config.cursor_row_field is not None:
        return {"last_id": cursor}
    return {"cursor": cursor}


def mailtrap_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailtrapResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = MAILTRAP_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.incremental_param is not None:
        # Server-side lower bound (filters[sent_after] / start_time). The framework injects the
        # watermark (db_incremental_field_last_value) once and re-sends it on every page, so cursor
        # pagination never walks past it into already-synced history. On a full refresh the pipeline
        # passes a None watermark, which _format_timestamp keeps None and requests drops.
        cursor_field = config.incremental_fields[0]["field"] if config.incremental_fields else config.partition_key
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": cursor_field,
            "initial_value": None,
            "convert": _format_timestamp,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MAILTRAP_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_token, "name": "Api-Token", "location": "header"},
            "paginator": _build_paginator(config),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_key,
                    # A 200 whose body isn't the expected list shape (bare list where a wrapper is
                    # expected, missing data key, or a wrapped body where a bare array is expected)
                    # is a transient/malformed payload — retry rather than ingest garbage.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = _initial_paginator_state(config, resume.cursor)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        cursor = state.get("cursor") if state.get("cursor") is not None else state.get("last_id")
        if cursor is not None:
            resumable_source_manager.save_state(MailtrapResumeConfig(cursor=str(cursor)))

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
        # email_logs is documented newest-first; suppressions ordering is undocumented. "desc" makes
        # the pipeline commit the incremental watermark only after a sync completes, which is safe
        # in both cases.
        sort_mode="desc" if config.incremental_param else "asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{MAILTRAP_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Api-Token": api_token, **_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Mailtrap API token"
    if status is None:
        return False, "Could not connect to Mailtrap"
    return False, f"Mailtrap returned HTTP {status}"
