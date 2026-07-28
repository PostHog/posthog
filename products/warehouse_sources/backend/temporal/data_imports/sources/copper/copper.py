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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import (
    COPPER_DEFAULT_PAGE_SIZE,
    COPPER_ENDPOINTS,
    CopperEndpointConfig,
)

COPPER_BASE_URL = "https://api.copper.com/developer_api/v1"
# Copper requires this header on every request; "developer" is the documented value for API-key auth.
COPPER_APPLICATION = "developer"

# Maps an advertised incremental field to its server-side filter param and sort column.
# Copper's search endpoints filter by `minimum_modified_date` / `minimum_created_date`
# (inclusive Unix-epoch-seconds bounds) and sort by `date_modified` / `date_created`.
INCREMENTAL_FIELD_TO_PARAMS: dict[str, tuple[str, str]] = {
    "date_modified": ("minimum_modified_date", "date_modified"),
    "date_created": ("minimum_created_date", "date_created"),
}


@dataclasses.dataclass
class CopperResumeConfig:
    page_number: int


class CopperPageNumberPaginator(BasePaginator):
    """Page-number pagination carried inside the POST search body.

    Copper's `/search` endpoints page via a `page_number` field in the JSON body and return a bare
    array. A page shorter than `page_size` (or an empty page) is the last one, so we stop without
    paying for one extra empty-page request. Resume persists the next page to fetch.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page = page

    def _inject(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["page_number"] = self.page

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # A short or empty page is the last one — Copper has no total count to consult.
        if not data or len(data) < self.page_size:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def _headers(user_email: str) -> dict[str, str]:
    # The secret access token travels via framework `auth` (APIKeyAuth) so its value is redacted from
    # logs; only these non-secret headers are set on the client.
    return {
        "X-PW-Application": COPPER_APPLICATION,
        "X-PW-UserEmail": user_email,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> int | None:
    """Coerce the stored incremental watermark into the Unix-epoch-seconds Copper expects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        # Treat naive datetimes as UTC so the epoch cutoff doesn't shift with the host timezone.
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_search_body(
    config: CopperEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    page_size: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {"page_size": page_size}

    if should_use_incremental_field and incremental_field in INCREMENTAL_FIELD_TO_PARAMS:
        min_param, sort_field = INCREMENTAL_FIELD_TO_PARAMS[incremental_field]
        body["sort_by"] = sort_field
        body["sort_direction"] = "asc"
        last_value = _to_unix_seconds(db_incremental_field_last_value)
        if last_value is not None:
            # Inclusive bound: the boundary row is re-fetched and deduped by merge on primary key.
            body[min_param] = last_value
    elif config.full_refresh_sort:
        body["sort_by"] = config.full_refresh_sort
        body["sort_direction"] = "asc"

    return body


def validate_credentials(api_key: str, user_email: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{COPPER_BASE_URL}/account",
        headers={"X-PW-AccessToken": api_key, **_headers(user_email)},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Copper credentials. Check your API key and the email it belongs to."
    if status is None:
        return False, "Could not reach Copper to validate credentials. Please try again."
    return False, f"Copper credential check failed with status {status}"


def copper_source(
    api_key: str,
    user_email: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = COPPER_ENDPOINTS[endpoint]

    body: dict[str, Any] | None
    paginator: BasePaginator
    if config.paginated:
        body = _build_search_body(
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
            COPPER_DEFAULT_PAGE_SIZE,
        )
        paginator = CopperPageNumberPaginator(page_size=COPPER_DEFAULT_PAGE_SIZE)
    else:
        # Reference endpoints are plain unpaginated GET collections returned as one array.
        body = None
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": COPPER_BASE_URL,
            "headers": _headers(user_email),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-PW-AccessToken", "location": "header"},
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "method": config.method,
                    # Copper responses are bare JSON arrays, so there's no data_selector.
                    "json": body,
                    "paginator": paginator,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page_number}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(CopperResumeConfig(page_number=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if config.paginated else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        partition_keys=config.partition_keys,
        sort_mode="asc",
    )
