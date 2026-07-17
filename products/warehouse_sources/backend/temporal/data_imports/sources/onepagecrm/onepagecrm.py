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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ONEPAGECRM_ENDPOINTS,
    OnepagecrmEndpointConfig,
)

ONEPAGECRM_BASE_URL = "https://app.onepagecrm.com/api/v3"
# List endpoints accept a `per_page` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm the user ID / API key pair is genuine. The key grants read access
# to the whole account, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/contacts"


@dataclasses.dataclass
class OnepagecrmResumeConfig:
    # Next page to fetch (1-based). Page numbering is only stable for a fixed query, so the
    # `modified_since` anchor the run started with is persisted alongside it — resuming with a
    # fresher watermark would renumber the pages and skip rows.
    page: int = 1
    modified_since: str | None = None


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for the `modified_since` filter.

    OnePageCRM returns `modified_at` as an ISO 8601 string, so the persisted watermark can be a
    string or a parsed datetime depending on how the column was typed; ints are accepted
    defensively.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    return None


def modified_since_anchor(db_incremental_field_last_value: Any) -> str | None:
    """Compute the `modified_since` value for an incremental run.

    The anchor is backed off by one second: the API doesn't document whether the filter is
    inclusive, and re-fetching the boundary second is free (merge dedupes on `id`) while missing
    it would drop rows.
    """
    epoch = _to_epoch(db_incremental_field_last_value)
    if epoch is None:
        return None
    return str(max(0, epoch - 1))


class OnepagecrmPaginator(PageNumberPaginator):
    """Page-number pagination for OnePageCRM list endpoints.

    Responses carry `data.max_page` (the last page number); pagination stops after it. As a
    defensive fallback for responses that omit `max_page`, a page shorter than the requested
    `per_page` also terminates. An empty page always stops.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page=1, page_param="page", total_path="data.max_page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self.stop_after_empty_page and (data is None or len(data) == 0):
            self._has_next_page = False
            return

        self.page += 1

        max_page = self._read_max_page(response)
        if isinstance(max_page, int):
            # `self.page` now points at the NEXT page; the last valid page is `max_page`
            # (base_page=1), matching the hand-rolled `page >= max_page` stop.
            self._has_next_page = self.page <= max_page
            return

        # `max_page` absent — fall back to short-page termination.
        self._has_next_page = data is not None and len(data) >= self._page_size

    def _read_max_page(self, response: Response) -> Optional[int]:
        try:
            values = find_values(self.total_path, response.json())
        except Exception:
            return None
        if values and isinstance(values[0], int):
            return values[0]
        return None


def _unwrap_map(item_key: Optional[str]):
    # Paginated list responses wrap each record under its singular resource name
    # (e.g. {"contact": {...}}); config endpoints vary — users/statuses wrap, lead_sources doesn't.
    def _map(record: dict[str, Any]) -> dict[str, Any]:
        if item_key is not None and isinstance(record.get(item_key), dict):
            return record[item_key]
        return record

    return _map


def _build_params(
    config: OnepagecrmEndpointConfig,
    modified_since: str | None,
    should_use_incremental_field: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        # `page` is injected by the paginator; only the fixed page size is a static param.
        params["per_page"] = PAGE_SIZE
    if config.supports_sort:
        # Incremental runs sort by the cursor field so the per-batch watermark advances
        # monotonically (order=asc). Full-refresh runs sort by the immutable created_at so rows
        # never shift into already-fetched pages mid-sync.
        params["sort_by"] = "modified_at" if should_use_incremental_field else "created_at"
        params["order"] = "asc"
    if should_use_incremental_field and modified_since is not None:
        params["modified_since"] = modified_since
    return params


def onepagecrm_source(
    user_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OnepagecrmResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONEPAGECRM_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        initial_page = resume.page
        # A fresher watermark must NOT replace the saved anchor: page numbers are only stable for
        # the query the run started with.
        modified_since = resume.modified_since
    else:
        initial_page = 1
        modified_since = (
            modified_since_anchor(db_incremental_field_last_value) if should_use_incremental_field else None
        )

    if config.paginated:
        paginator = OnepagecrmPaginator(page_size=PAGE_SIZE)
        data_selector = f"data.{config.data_key}"
    else:
        paginator = SinglePagePaginator()
        data_selector = "data"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ONEPAGECRM_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Framework Basic auth so the derived credential is redacted from logs and error
            # messages instead of a hand-built Authorization header.
            "auth": {"type": "http_basic", "username": user_id, "password": api_key},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, modified_since, should_use_incremental_field),
                    "data_selector": data_selector,
                    # A 200 body without the expected data key/list means the response shape
                    # changed — fail loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
                "data_map": _unwrap_map(config.item_key),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = {"page": initial_page} if resume is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it. The anchor the
        # run started with is stored alongside the page so a resume re-issues the identical query.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(
                OnepagecrmResumeConfig(page=int(state["page"]), modified_since=modified_since)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
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
    )


def validate_credentials(user_id: str, api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the user ID / API key pair.

    The API key grants account-wide read access, so one probe validates every list endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ONEPAGECRM_BASE_URL}{DEFAULT_PROBE_PATH}?per_page=1",
        auth=HttpBasicAuth(username=user_id, password=api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid OnePageCRM user ID or API key"
    if status is None:
        return False, "Could not connect to OnePageCRM"
    return False, f"OnePageCRM returned HTTP {status}"
