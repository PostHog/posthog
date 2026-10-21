import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import (
    RECURLY_BASE_URLS,
    RECURLY_ENDPOINTS,
)

# Pinning the API version is required — Recurly rejects requests without it.
RECURLY_API_VERSION = "v2021-02-25"
# Recurly caps list endpoints at 200 records per page.
PAGE_LIMIT = 200
DEFAULT_SORT_FIELD = "updated_at"
# `sort` and `begin_time` only accept these timestamp columns.
VALID_SORT_FIELDS = ("created_at", "updated_at")


@dataclasses.dataclass(frozen=True)
class RecurlyResumeConfig:
    # Top-level endpoints: the cursor of the next page.
    next_cursor: str = ""
    # Fan-out endpoints: the framework's dependent-resource resume state
    # (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: Optional[dict[str, Any]] = None


@dataclasses.dataclass(frozen=True)
class RecurlyFanout:
    # Child path param -> field of the (mapped) parent row that fills it. Each field is also
    # copied onto the child rows under the path param's name.
    path_bindings: dict[str, str]
    child_params: dict[str, Any]
    parent_data_map: Optional[Callable[[dict[str, Any]], list[dict[str, Any]]]] = None


def _usage_add_ons(subscription: dict[str, Any]) -> list[dict[str, Any]]:
    """Explode a subscription into one row per usage add-on, which is what the usage endpoint is keyed on."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for subscription_add_on in subscription.get("add_ons") or []:
        add_on = subscription_add_on.get("add_on") or {}
        add_on_id = add_on.get("id")
        # Fixed add-ons have no usage records, so requesting them only wastes a call.
        if add_on.get("add_on_type") != "usage" or not add_on_id or add_on_id in seen:
            continue
        seen.add(add_on_id)
        rows.append({"subscription_id": subscription["id"], "add_on_id": add_on_id})
    return rows


RECURLY_FANOUTS: dict[str, RecurlyFanout] = {
    # The v2021-02-25 spec declares no `limit` or `order` for this list, and Recurly 400s on
    # undeclared params (see `gift_cards`), so it is listed with the defaults.
    "coupon_redemptions": RecurlyFanout(path_bindings={"account_id": "id"}, child_params={}),
    "usage": RecurlyFanout(
        path_bindings={"subscription_id": "subscription_id", "add_on_id": "add_on_id"},
        child_params={"limit": PAGE_LIMIT, "sort": "recorded_timestamp", "order": "asc"},
        parent_data_map=_usage_add_ons,
    ),
}


def _headers() -> dict[str, str]:
    return {"Accept": f"application/vnd.recurly.{RECURLY_API_VERSION}"}


def _base_url(region: str) -> str:
    return RECURLY_BASE_URLS.get(region, RECURLY_BASE_URLS["us"])


def _format_datetime(value: Any) -> Optional[str]:
    """Format an incremental cursor value as an ISO8601 timestamp for `begin_time`.

    Recurly treats a partial timestamp without a timezone as UTC, so we always
    emit an explicit UTC value.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        # Promote a bare date to midnight UTC so begin_time is always a full datetime.
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


def _extract_cursor(next_path: Optional[str]) -> Optional[str]:
    """Pull the `cursor` query param out of the `next` path Recurly returns."""
    if not next_path:
        return None
    cursors = parse_qs(urlparse(next_path).query).get("cursor")
    return cursors[0] if cursors else None


class RecurlyPaginator(BasePaginator):
    """Cursor pagination for Recurly's list endpoints.

    Recurly returns ``{"has_more": bool, "next": "<path>?cursor=...", "data": [...]}``.
    The ``next`` value is a relative path, so rather than chasing the URL we extract
    its ``cursor`` and re-apply it as a query param on the same request — this keeps
    the original ``sort``/``order``/``begin_time`` params intact and makes the cursor
    trivially resumable.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._next_cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["cursor"] = self._next_cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._next_cursor = None
        try:
            body = response.json()
        except ValueError:
            body = None

        if not isinstance(body, dict) or not body.get("has_more"):
            self._has_next_page = False
            return

        cursor = _extract_cursor(body.get("next"))
        if cursor:
            self._next_cursor = cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        if self._next_cursor is not None:
            request.params["cursor"] = self._next_cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_cursor is not None and self._has_next_page:
            return {"next_cursor": self._next_cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_cursor = state.get("next_cursor")
        if next_cursor is not None:
            self._next_cursor = str(next_cursor)
            self._has_next_page = True


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    config = RECURLY_ENDPOINTS[endpoint]
    incremental = should_use_incremental_field and config.supports_incremental

    if not config.supports_list_params:
        # This endpoint 400s on any query parameter, so it can't be paginated with a
        # `limit`, sorted, or filtered by `begin_time` — just take whatever Recurly returns.
        params: dict[str, Any] = {}
    else:
        if incremental:
            # Sort by the cursor the user chose so `begin_time` and the watermark agree.
            # Ascending order is mandatory: Recurly warns that descending `updated_at`
            # lets concurrently-updated rows slip behind the cursor and never return.
            sort_field = incremental_field if incremental_field in VALID_SORT_FIELDS else DEFAULT_SORT_FIELD
        else:
            # Full refresh: a stable ascending `created_at` sort avoids page-boundary
            # skips/duplicates if rows are inserted mid-sync.
            sort_field = "created_at"

        params = {
            "limit": PAGE_LIMIT,
            "sort": sort_field,
            "order": "asc",
        }
        if incremental and db_incremental_field_last_value is not None:
            params["begin_time"] = _format_datetime(db_incremental_field_last_value)

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def _client_config(api_key: str, region: str) -> ClientConfig:
    return {
        "base_url": _base_url(region),
        "headers": _headers(),
        "auth": {
            "type": "http_basic",
            "username": api_key,
            "password": "",
        },
        "paginator": RecurlyPaginator(),
    }


def _fanout_resource(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecurlyResumeConfig],
) -> Resource:
    config = RECURLY_ENDPOINTS[endpoint]
    fanout = RECURLY_FANOUTS[endpoint]
    parent_name = config.parent
    assert parent_name is not None

    parent: EndpointResource = {
        "name": parent_name,
        "table_name": parent_name,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": "data",
            "path": RECURLY_ENDPOINTS[parent_name].path,
            "params": {"limit": PAGE_LIMIT, "sort": "created_at", "order": "asc"},
        },
        "table_format": "delta",
    }
    if fanout.parent_data_map is not None:
        parent["data_map"] = fanout.parent_data_map

    child_params: dict[str, Any] = {
        param: {"type": "resolve", "resource": parent_name, "field": field}
        for param, field in fanout.path_bindings.items()
    }
    child_params.update(fanout.child_params)
    child: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "include_from_parent": list(fanout.path_bindings.values()),
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
            "params": child_params,
            # A parent removed between the listing and its child fetch must not fail the whole sync.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "table_format": "delta",
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, region),
        "resource_defaults": {},
        "resources": [parent, child],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.fanout_state:
            initial_paginator_state = resume_config.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(RecurlyResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child_resource = next(r for r in resources if r.name == endpoint)
    return child_resource.add_map(
        rename_parent_fields(parent_name, {field: param for param, field in fanout.path_bindings.items()})
    )


def recurly_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecurlyResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> Resource:
    if RECURLY_ENDPOINTS[endpoint].parent is not None:
        return _fanout_resource(api_key, region, endpoint, team_id, job_id, resumable_source_manager)

    incremental = should_use_incremental_field and RECURLY_ENDPOINTS[endpoint].supports_incremental

    config: RESTAPIConfig = {
        "client": _client_config(api_key, region),
        "resource_defaults": {
            "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        },
        "resources": [
            get_resource(endpoint, should_use_incremental_field, incremental_field, db_incremental_field_last_value)
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.next_cursor:
            initial_paginator_state = {"next_cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page; the Redis TTL handles cleanup on completion.
        if state and state.get("next_cursor"):
            resumable_source_manager.save_state(RecurlyResumeConfig(next_cursor=str(state["next_cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, Optional[str]]:
    try:
        res = make_tracked_session().get(
            f"{_base_url(region)}/accounts",
            params={"limit": 1},
            headers=_headers(),
            auth=(api_key, ""),
            timeout=30,
        )
    except Exception as e:
        return False, f"Could not reach Recurly ({e}). Please check your network and region, then try again."

    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        return (
            False,
            "Recurly rejected the API key (401 Unauthorized). Create a private API key under "
            "Integrations > API Credentials in Recurly and confirm the selected region matches your site.",
        )
    if res.status_code == 403:
        return (
            False,
            "The Recurly API key is valid but lacks permission to read this site (403 Forbidden). "
            "Check the key's permissions and try again.",
        )
    return False, f"Recurly returned an unexpected status ({res.status_code}) while validating credentials."
