import logging
import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.settings import (
    MAX_PAGE,
    OPENCORPORATES_ENDPOINTS,
    PER_PAGE,
)

logger = logging.getLogger(__name__)

OPENCORPORATES_BASE_URL = "https://api.opencorporates.com/v0.4"


@dataclasses.dataclass(frozen=True)
class OpencorporatesResumeConfig:
    # Next 1-indexed page to fetch — OpenCorporates uses page-number pagination.
    next_page: int


def _format_incremental_filter(value: Any) -> str:
    """Format the incremental cursor as OpenCorporates' open-ended date-range filter.

    The `updated_at`/`created_at` facet filters only have day granularity (documented as
    `2009-08-22:2012-01-08`), so an open-ended `<date>:` range re-fetches the watermark day in
    full each run; merge on the primary key dedupes the overlap.
    """
    if isinstance(value, datetime):
        return f"{value.date().isoformat()}:"
    if isinstance(value, date):
        return f"{value.isoformat()}:"
    return f"{str(value)[:10]}:"


class OpencorporatesPaginator(PageNumberPaginator):
    """Page-number pagination capped at OpenCorporates' documented page<=100 limit.

    `results.total_pages` stops us after the last real page when present; the base class's
    `stop_after_empty_page` covers responses (e.g. `officers/search`) that omit it.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page", total_path="results.total_pages", maximum_page=MAX_PAGE)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        page_before = self.page
        super().update_state(response, data)
        if not self._has_next_page and data and page_before == self.maximum_page:
            logger.info(
                "OpenCorporates pagination hit the API's %s-page cap; some matching rows may not "
                "have been fetched. Narrow the search term or jurisdiction to reach the rest.",
                MAX_PAGE,
            )


def opencorporates_source(
    api_token: str,
    query: str,
    jurisdiction_code: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpencorporatesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENCORPORATES_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"q": query, "per_page": PER_PAGE}
    if jurisdiction_code:
        params["jurisdiction_code"] = jurisdiction_code
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["updated_at"] = _format_incremental_filter(db_incremental_field_last_value)
        # Date facets are only ever returned newest-first — there is no ascending option.
        params["order"] = "updated_at"

    resource: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
        },
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "table_format": "delta",
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": OPENCORPORATES_BASE_URL,
            # api_token rides in the query string (the API's only auth method); the framework auth
            # redacts its value from every logged URL, captured sample, and raised error message.
            "auth": {"type": "api_key", "api_key": api_token, "name": "api_token", "location": "query"},
            "paginator": OpencorporatesPaginator(),
        },
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(OpencorporatesResumeConfig(next_page=int(state["page"])))

    rest_resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: rest_resource,
        primary_keys=config.primary_keys,
        # Companies is requested with order=updated_at, which OpenCorporates can only return
        # newest-first; the watermark is finalised once the whole (already server-filtered) sync
        # completes rather than checkpointed per batch. Irrelevant for full-refresh endpoints.
        sort_mode="desc",
        column_hints=rest_resource.column_hints,
        **partition_kwargs,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    # `/account_status` is a cheap, side-effect-free probe that the token is genuine and reports
    # remaining quota without spending it against a search endpoint.
    session = make_tracked_session(redact_values=(api_token,))
    try:
        response = session.get(
            f"{OPENCORPORATES_BASE_URL}/account_status",
            params={"api_token": api_token},
            timeout=10,
        )
    except Exception:
        return False, "Could not connect to OpenCorporates. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 403:
        # The token is genuine — the account's request quota is just exhausted right now. Don't
        # block source creation on a quota that resets daily/monthly.
        return True, None
    if response.status_code == 401:
        return False, "Invalid OpenCorporates API token"
    return False, f"OpenCorporates returned an unexpected response (HTTP {response.status_code})"
