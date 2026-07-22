import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from dateutil import parser
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.settings import (
    ACCOUNTS,
    DEFAULT_UTILIZATION_START_DATE,
    UTILIZATION_WINDOW_DAYS,
    WASABI_BASE_URL,
    WASABI_ENDPOINTS,
    WasabiEndpointConfig,
)


@dataclasses.dataclass
class WasabiResumeConfig:
    # Opaque paginator resume snapshot: {"next_from": ...} for date-windowed endpoints,
    # the framework's {"completed"/"current"/"child_state"} shape for the fan-out.
    paginator_state: dict[str, Any]


class WasabiDateWindowPaginator(BasePaginator):
    """Walks a WACA utilization endpoint in ascending from/to date windows.

    WACA list endpoints return the entire (filtered) result set in one response with no
    cursor, so windowing by date bounds response sizes and gives us a resumable position.
    The from/to filters are treated as inclusive dates (Wasabi doesn't document
    inclusivity, but its own examples span both boundary days), so consecutive windows
    advance by a full window and never overlap.
    """

    def __init__(self, start_date: date, window_days: int = UTILIZATION_WINDOW_DAYS) -> None:
        super().__init__()
        self._window_days = window_days
        self._window_start = min(start_date, self._today())

    @staticmethod
    def _today() -> date:
        return datetime.now(UTC).date()

    def _window_end(self) -> date:
        return min(self._window_start + timedelta(days=self._window_days - 1), self._today())

    def _apply_window(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["from"] = self._window_start.isoformat()
        request.params["to"] = self._window_end().isoformat()

    def init_request(self, request: Request) -> None:
        self._apply_window(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # Empty windows still advance: utilization data can exist for later dates even
        # when a window has no rows (e.g. before the first sub-account was created).
        self._has_next_page = self._window_end() < self._today()

    def update_request(self, request: Request) -> None:
        if not self._has_next_page:
            return
        self._window_start = self._window_end() + timedelta(days=1)
        self._apply_window(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"next_from": self._window_start.isoformat()}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_from = state.get("next_from")
        if next_from:
            self._window_start = min(date.fromisoformat(str(next_from)), self._today())


def _start_date(should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]) -> date:
    last_value = db_incremental_field_last_value
    if should_use_incremental_field and last_value is not None:
        if isinstance(last_value, str):
            try:
                last_value = parser.parse(last_value)
            except (ValueError, OverflowError):
                last_value = None
        as_datetime = coerce_datetime_to_utc(last_value)
        if as_datetime is not None:
            return as_datetime.date()
    return date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": WASABI_BASE_URL,
        # WACA expects the raw API key as the Authorization header value (no Bearer prefix).
        "auth": {"type": "api_key", "name": "Authorization", "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
    }


def _make_source_response(endpoint_config: WasabiEndpointConfig, resource: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        # Date windows walk oldest-first, so the per-batch max of the incremental field
        # advances monotonically across batches.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def wasabi_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WasabiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = WASABI_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist mid-walk positions; the Redis TTL handles cleanup on completion.
        if state:
            resumable_source_manager.save_state(WasabiResumeConfig(paginator_state=state))

    if endpoint_config.parent is not None:
        parent_config = WASABI_ENDPOINTS[endpoint_config.parent]
        # Fan-out: iterate the sub-account list and fetch the child endpoint per account.
        # Child rows natively carry AcctNum, so no parent-field injection is needed.
        resources: list[str | EndpointResource] = [
            {
                "name": parent_config.name,
                "table_name": parent_config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": parent_config.path,
                    "data_selector": "$",
                    "paginator": SinglePagePaginator(),
                },
                "table_format": "delta",
            },
            {
                "name": endpoint_config.name,
                "table_name": endpoint_config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": {
                        "acct_num": {"type": "resolve", "resource": parent_config.name, "field": "AcctNum"},
                    },
                    "data_selector": "$",
                    "paginator": SinglePagePaginator(),
                },
                "table_format": "delta",
            },
        ]
        config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": {},
            "resources": resources,
        }
        all_resources = rest_api_resources(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        child_resource = next(r for r in all_resources if r.name == endpoint_config.name)
        return _make_source_response(endpoint_config, child_resource)

    if endpoint_config.date_windowed:
        paginator: BasePaginator = WasabiDateWindowPaginator(
            start_date=_start_date(should_use_incremental_field, db_incremental_field_last_value)
        )
    else:
        paginator = SinglePagePaginator()

    single_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint_config.name,
                "table_name": endpoint_config.name,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                if should_use_incremental_field
                else "replace",
                "endpoint": {
                    "path": endpoint_config.path,
                    "data_selector": "$",
                    "paginator": paginator,
                },
                "table_format": "delta",
            }
        ],
    }

    resource = rest_api_resource(
        single_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, resource)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    res = make_tracked_session(redact_values=(api_key,)).get(
        f"{WASABI_BASE_URL}{WASABI_ENDPOINTS[ACCOUNTS].path}",
        headers={"Authorization": api_key, "Accept": "application/json"},
        timeout=30,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code in (401, 403):
        # WACA returns 403 with {"Msg": "You are not permitted to complete that action"} for bad keys.
        return (
            False,
            "Wasabi rejected the API key. Check that Wasabi Account Control API access is enabled on your Control Account and the key is valid.",
        )
    return False, f"Wasabi API returned an unexpected response (HTTP {res.status_code})"
