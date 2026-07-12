"""Maxio (Advanced Billing / Chargify) API transport: auth, pagination, resource assembly."""

import re
import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.settings import (
    ENDPOINTS,
    MAXIO_BASE_URLS,
    PAGE_SIZE,
)


@dataclasses.dataclass
class MaxioResumeConfig:
    endpoint: str
    next_page: int


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Maxio site subdomain.

    Users frequently paste the full host ("acme.chargify.com") or a URL
    ("https://acme.chargify.com/") into the subdomain field. Without normalizing, the
    base URL would end up with a doubled host that can never resolve.
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    subdomain = subdomain.split("/", 1)[0]
    return re.sub(r"\.(chargify\.com|ebilling\.maxio\.com)$", "", subdomain, flags=re.IGNORECASE)


def get_base_url(subdomain: str, region: str) -> str:
    template = MAXIO_BASE_URLS.get(region, MAXIO_BASE_URLS["us"])
    return template.format(subdomain=normalize_subdomain(subdomain))


def format_start_datetime(value: Any) -> str:
    """Format an incremental watermark for the `start_datetime` query param.

    The API documents the format as `YYYY-MM-DD HH:MM:SS`, interpreted in the site's
    timezone. We format in UTC; the schema-level lookback window covers the resulting
    skew (see settings.TIMEZONE_SKEW_LOOKBACK_SECONDS).
    """
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def to_since_id(value: Any) -> int:
    return int(value)


class MaxioPaginator(BasePaginator):
    """Page-number pagination (`page`/`per_page`, page starts at 1).

    The API signals the last page implicitly: a page with fewer rows than `per_page`
    (or no rows) is the final one. Supports seeding from resumable state so a restarted
    job continues from the last checkpointed page.
    """

    def __init__(self, page_size: int = PAGE_SIZE) -> None:
        super().__init__()
        self.page = 1
        self.page_size = page_size

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page
        request.params["per_page"] = self.page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) < self.page_size:
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"page": self.page}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def get_resource(endpoint_name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = ENDPOINTS[endpoint_name]

    params: dict[str, Any] = {**config.extra_params, **config.sort_params}

    if should_use_incremental_field:
        params.update(config.incremental_sort_params)
        if config.uses_since_id:
            # `since_id` is inclusive (>=), so the watermark row is re-fetched and
            # deduped by the merge on primary keys.
            params["since_id"] = {
                "type": "incremental",
                "cursor_path": "id",
                "initial_value": 0,
                "convert": to_since_id,
            }
        elif config.incremental_date_field:
            params["date_field"] = config.incremental_date_field
            params["start_datetime"] = {
                "type": "incremental",
                "cursor_path": config.incremental_date_field,
                "initial_value": "1970-01-01 00:00:00",
                "convert": format_start_datetime,
            }

    return {
        "name": endpoint_name,
        "table_name": endpoint_name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def maxio_source(
    api_key: str,
    subdomain: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MaxioResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(subdomain, region),
            "auth": {
                "type": "http_basic",
                "username": api_key,
                # The API only inspects the username; any non-empty password works.
                "password": "x",
            },
            "paginator": MaxioPaginator(),
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.endpoint == endpoint:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(MaxioResumeConfig(endpoint=endpoint, next_page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, subdomain: str, region: str) -> tuple[bool, str | None]:
    response = make_tracked_session().get(
        f"{get_base_url(subdomain, region)}/customers.json",
        params={"page": 1, "per_page": 1},
        auth=(api_key, "x"),
    )
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Maxio rejected the API key. Check that the key is valid for this site."
    if response.status_code == 404:
        return False, "Maxio site not found. Check the subdomain and hosting region."
    return False, f"Could not connect to Maxio (HTTP {response.status_code}). Check the subdomain and API key."
