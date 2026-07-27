import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.settings import CHARGIFY_ENDPOINTS
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

# Chargify sites use HTTP Basic auth with the API key as the username and any value as the
# password ('x' is the documented convention).
CHARGIFY_BASIC_PASSWORD = "x"

# Chargify pages are 1-indexed.
BASE_PAGE = 1


@dataclasses.dataclass
class ChargifyResumeConfig:
    next_page: int


def base_url(subdomain: str) -> str:
    """Per-site hostname: each Chargify merchant site has its own subdomain."""
    return f"https://{subdomain}.chargify.com"


class ChargifyPaginator(PageNumberPaginator):
    """Page-number paginator that can persist and restore its cursor.

    Chargify list endpoints return a bare array with no total count, so pagination walks
    ``page`` upward until an empty page is returned (``stop_after_empty_page``). The resume
    state is simply the next page number to fetch.
    """

    def __init__(self, page: Optional[int] = None) -> None:
        super().__init__(
            base_page=BASE_PAGE,
            page=page,
            page_param="page",
            # Bare-array responses carry no "total" field, so terminate on the first empty page.
            total_path=None,
            stop_after_empty_page=True,
        )

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # ``update_state`` has already advanced ``self.page`` to the next page to fetch.
        if self._has_next_page:
            return {"page": self.page}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("page")
        if next_page is not None:
            self.page = int(next_page)
            self._has_next_page = True


def get_resource(name: str) -> EndpointResource:
    endpoint = CHARGIFY_ENDPOINTS[name]
    return {
        "name": endpoint.name,
        "table_name": endpoint.name.lower(),
        # Every endpoint is full refresh today (see settings.INCREMENTAL_FIELDS), so we
        # fully replace the table each sync.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": endpoint.data_selector,
            "path": endpoint.path,
            "params": dict(endpoint.params),
        },
        "table_format": "delta",
    }


def chargify_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChargifyResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(subdomain),
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": CHARGIFY_BASIC_PASSWORD,
            },
            "paginator": ChargifyPaginator(),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; Redis TTL handles cleanup
        # once the sync completes. Saving AFTER each yielded batch means a crash re-yields
        # the last page rather than skipping it (the merge dedupes on primary key).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ChargifyResumeConfig(next_page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, subdomain: str) -> bool:
    res = make_tracked_session().get(
        f"{base_url(subdomain)}/customers.json",
        params={"per_page": 1},
        auth=(api_key, CHARGIFY_BASIC_PASSWORD),
    )
    return res.status_code == 200
