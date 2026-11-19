"""Maxio (Advanced Billing / Chargify) API transport: auth, pagination, resource assembly."""

import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.maxio.settings import (
    ENDPOINTS,
    MAXIO_BASE_URLS,
    PAGE_SIZE,
    MaxioEndpointConfig,
    MaxioFanoutConfig,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
    ResumableSourceManager,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
)

FANOUT_PARENT = "subscription_components"


@dataclasses.dataclass(frozen=False)
class MaxioResumeConfig:
    endpoint: str
    next_page: int | None = None
    # Resume state of a fan-out endpoint, as the REST framework reports it.
    fanout_state: dict[str, Any] | None = None


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


def format_since_date(value: Any) -> str:
    """Format an incremental watermark for the date-only `since_date` query param."""
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value
        return dt.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


class MaxioPaginator(BasePaginator):
    """Page-number pagination (`page`/`per_page`, page starts at 1).

    The API signals the last page implicitly: a page with fewer rows than `per_page`
    (or no rows) is the final one. Supports seeding from resumable state so a restarted
    job continues from the last checkpointed page.
    """

    def __init__(self, page_size: int = PAGE_SIZE, send_page_size: bool = True) -> None:
        super().__init__()
        self.page = 1
        self.page_size = page_size
        self.send_page_size = send_page_size

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page
        if self.send_page_size:
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


def _paginator_for(config: MaxioEndpointConfig) -> MaxioPaginator:
    return MaxioPaginator(page_size=config.page_size, send_page_size=config.sends_page_size)


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
        elif config.since_date_field:
            params["since_date"] = {
                "type": "incremental",
                "cursor_path": config.since_date_field,
                "initial_value": "1970-01-01",
                "convert": format_since_date,
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
            "paginator": _paginator_for(config),
        },
        "table_format": "delta",
    }


def _fanout_parent_resource(fanout: MaxioFanoutConfig) -> EndpointResource:
    parent = get_resource(FANOUT_PARENT, should_use_incremental_field=False)
    kinds = fanout.component_kinds
    parent["data_map"] = lambda row: row if row.get("kind") in kinds else []
    return parent


def _fill_ids_from_parent(row: dict[str, Any]) -> dict[str, Any]:
    # The ids are part of the primary key, so a child row that omits them takes the parent's.
    for field in ("subscription_id", "component_id"):
        parent_value = row.pop(f"_{FANOUT_PARENT}_{field}", None)
        if row.get(field) is None:
            row[field] = parent_value
    return row


def _fanout_child_resource(endpoint_name: str, should_use_incremental_field: bool) -> EndpointResource:
    child = get_resource(endpoint_name, should_use_incremental_field)
    endpoint = child["endpoint"]
    assert isinstance(endpoint, dict)
    endpoint["params"] = {
        **(endpoint.get("params") or {}),
        **{
            field: {"type": "resolve", "resource": FANOUT_PARENT, "field": field}
            for field in ("subscription_id", "component_id")
        },
    }
    # A subscription deleted after the parent listing returns 404; it has no rows to read.
    endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    child["include_from_parent"] = ["subscription_id", "component_id"]
    child["resume_parent_pagination"] = True
    return child


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
    client: ClientConfig = {
        "base_url": get_base_url(subdomain, region),
        "auth": {
            "type": "http_basic",
            "username": api_key,
            # The API only inspects the username; any non-empty password works.
            "password": "x",
        },
        "paginator": MaxioPaginator(),
    }

    fanout = ENDPOINTS[endpoint].fanout
    if fanout is not None:
        return _maxio_fanout_source(
            client=client,
            endpoint=endpoint,
            fanout=fanout,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )

    config: RESTAPIConfig = {
        "client": client,
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
        if resume_config is not None and resume_config.endpoint == endpoint and resume_config.next_page is not None:
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


def _maxio_fanout_source(
    *,
    client: ClientConfig,
    endpoint: str,
    fanout: MaxioFanoutConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MaxioResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
):
    config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {},
        "resources": [
            _fanout_parent_resource(fanout),
            _fanout_child_resource(endpoint, should_use_incremental_field),
        ],
    }

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.endpoint == endpoint:
            initial_state = resume_config.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(MaxioResumeConfig(endpoint=endpoint, fanout_state=state))

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    child = next(r for r in resources if r.name == endpoint)
    return child.add_map(_fill_ids_from_parent)


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
