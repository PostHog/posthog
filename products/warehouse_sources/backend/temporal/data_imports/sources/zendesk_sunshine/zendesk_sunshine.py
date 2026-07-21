import re
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

from dateutil import parser as dateutil_parser
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_QUERY_WINDOW_START,
    MAX_PAGES_PER_QUERY_WINDOW,
    QUERY_PATH,
    RECORDS_PAGE_SIZE,
    ZENDESK_SUNSHINE_ENDPOINTS,
    ZendeskSunshineEndpointConfig,
)


@dataclasses.dataclass
class ZendeskSunshineResumeConfig:
    """Generic resume envelope.

    `state` holds whichever checkpoint shape the endpoint produces: a paginator snapshot for
    top-level endpoints, the framework's `{completed, current, child_state}` fan-out shape for
    dependent endpoints, or the incremental object records loop's shape (which adds
    `window_start`). Each schema syncs as its own job, so the shapes never share a Redis key.
    """

    state: dict[str, Any]


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Zendesk subdomain label.

    Users frequently paste the full host ("nibbles.zendesk.com") or a URL
    ("https://nibbles.zendesk.com/") into the subdomain field; without normalizing, the
    base URL would carry a doubled host.
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    subdomain = subdomain.split("/", 1)[0]
    return re.sub(r"\.zendesk\.com$", "", subdomain, flags=re.IGNORECASE)


def get_base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.zendesk.com/api/sunshine/"


def to_query_datetime(value: Any) -> str | None:
    """Format a watermark or record timestamp as the `yyyy-MM-dd HH:mm:ss.SSS` (UTC) string
    the query endpoint's `_updated_at` range filter expects."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, OverflowError):
            return None
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return None
    return normalized.strftime("%Y-%m-%d %H:%M:%S.") + f"{normalized.microsecond // 1000:03d}"


class SunshineLinksPaginator(JSONResponsePaginator):
    """Follows the `links.next` URL Sunshine list endpoints return, absolutized against the
    account's base URL (the docs don't guarantee whether the link is absolute or relative)."""

    def __init__(self, base_url: str) -> None:
        super().__init__(next_url_path="links.next")
        self._base_url = base_url

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url:
            self._next_url = urljoin(self._base_url, self._next_url)


class SunshineObjectQueryPaginator(SunshineLinksPaginator):
    """Cursor pagination for the POST `objects/query` search endpoint.

    Follows `links.next` like the other Sunshine endpoints, but this endpoint's cursor grows
    with every page and Zendesk rejects it past ~80 pages. Results are requested sorted
    `_updated_at asc`, so before hitting the cap we re-window: restart the query with
    `_updated_at.start` set to the newest `updated_at` seen so far. Boundary rows are
    re-fetched (the range start is inclusive) and deduped by the merge on `id`.
    """

    def __init__(
        self,
        base_url: str,
        window_start: str,
        page_size: int = RECORDS_PAGE_SIZE,
        max_pages_per_window: int = MAX_PAGES_PER_QUERY_WINDOW,
    ) -> None:
        super().__init__(base_url)
        self._query_url = urljoin(base_url, QUERY_PATH)
        self._page_size = page_size
        self._window_start = window_start
        self._max_pages_per_window = max_pages_per_window
        self._pages_in_window = 0
        self._last_updated_at: Optional[str] = None

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        self._apply_window(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        for row in data or []:
            # Rows arrive sorted `_updated_at asc`, so the last timestamped row is the max.
            if isinstance(row, dict) and row.get("updated_at"):
                self._last_updated_at = row["updated_at"]
        self._pages_in_window += 1
        if self._has_next_page and self._pages_in_window >= self._max_pages_per_window:
            next_start = to_query_datetime(self._last_updated_at)
            if next_start is None:
                raise ValueError(
                    "Zendesk Sunshine query pagination reached the per-window page limit but no row "
                    "carried a usable `updated_at` to re-window from"
                )
            if next_start == self._window_start:
                raise ValueError(
                    f"Zendesk Sunshine query window cannot advance: every row shares updated_at {next_start}"
                )
            self._window_start = next_start
            self._next_url = f"{self._query_url}?{urlencode({'per_page': self._page_size})}"
            self._pages_in_window = 0

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._apply_window(request)

    def _apply_window(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["_updated_at"] = {"start": self._window_start}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        state = super().get_resume_state()
        if state is None:
            return None
        return {**state, "window_start": self._window_start, "pages_in_window": self._pages_in_window}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        window_start = state.get("window_start")
        if window_start:
            self._window_start = window_start
        self._pages_in_window = int(state.get("pages_in_window") or 0)


def _client_config(subdomain: str, api_key: str, email_address: str) -> ClientConfig:
    return {
        "base_url": get_base_url(subdomain),
        "auth": {
            "type": "http_basic",
            # Zendesk API token auth requires the `{email}/token` username form.
            "username": f"{email_address}/token",
            "password": api_key,
        },
        "headers": {"Accept": "application/json"},
        # Pin pagination `links.next` URLs to the account's own host.
        "allowed_hosts": [],
    }


def _top_level_resource(endpoint_config: ZendeskSunshineEndpointConfig, base_url: str) -> EndpointResource:
    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": "replace",
        "endpoint": {
            "path": endpoint_config.path,
            "params": {"per_page": endpoint_config.page_size},
            "paginator": SunshineLinksPaginator(base_url),
            "data_selector": "data",
        },
        "table_format": "delta",
    }


def _fanout_resources(
    endpoint_config: ZendeskSunshineEndpointConfig,
    parent_config: ZendeskSunshineEndpointConfig,
    base_url: str,
) -> list[str | EndpointResource]:
    if endpoint_config.resolve_placeholder is None or endpoint_config.resolve_field is None:
        raise ValueError(f"Endpoint {endpoint_config.name} is not configured for fan-out")

    child_params: dict[str, Any] = {
        endpoint_config.resolve_placeholder: {
            "type": "resolve",
            "resource": parent_config.name,
            "field": endpoint_config.resolve_field,
        },
    }
    child_endpoint: Endpoint = {
        "path": endpoint_config.path,
        "params": child_params,
        "data_selector": "data",
    }
    if endpoint_config.single_page:
        child_endpoint["paginator"] = SinglePagePaginator()
    else:
        child_params["per_page"] = endpoint_config.page_size
        child_endpoint["paginator"] = SunshineLinksPaginator(base_url)

    child_resource: EndpointResource = {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": "replace",
        "include_from_parent": endpoint_config.include_from_parent,
        "endpoint": child_endpoint,
        "table_format": "delta",
    }
    return [_top_level_resource(parent_config, base_url), child_resource]


def _query_resource(object_type_key: str, window_start: str, base_url: str) -> EndpointResource:
    return {
        "name": "object_records",
        "table_name": "object_records",
        "write_disposition": {"disposition": "merge", "strategy": "upsert"},
        "endpoint": {
            "method": "POST",
            "path": QUERY_PATH,
            "params": {"per_page": RECORDS_PAGE_SIZE},
            "json": {
                "query": {"_type": {"$eq": object_type_key}},
                "sort_by": "_updated_at asc",
                "_updated_at": {"start": window_start},
            },
            "paginator": SunshineObjectQueryPaginator(base_url, window_start),
            "data_selector": "data",
        },
        "table_format": "delta",
    }


def _load_resume_state(
    resumable_source_manager: ResumableSourceManager[ZendeskSunshineResumeConfig],
) -> Optional[dict[str, Any]]:
    if not resumable_source_manager.can_resume():
        return None
    loaded = resumable_source_manager.load_state()
    return loaded.state if loaded is not None else None


def _make_resume_hook(
    resumable_source_manager: ResumableSourceManager[ZendeskSunshineResumeConfig],
) -> Callable[[Optional[dict[str, Any]]], None]:
    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's something to resume to; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(ZendeskSunshineResumeConfig(state=state))

    return save_checkpoint


def list_object_type_keys(subdomain: str, api_key: str, email_address: str) -> list[str]:
    """Fetch every legacy object type key, following `links.next` pagination."""
    base_url = get_base_url(subdomain)
    session = make_tracked_session(redact_values=(api_key,), headers={"Accept": "application/json"})
    session.auth = (f"{email_address}/token", api_key)

    keys: list[str] = []
    url: Optional[str] = urljoin(base_url, "objects/types")
    params: Optional[dict[str, Any]] = {"per_page": DEFAULT_PAGE_SIZE}
    while url:
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
        body = response.json() or {}
        keys.extend(item["key"] for item in body.get("data") or [] if isinstance(item, dict) and item.get("key"))
        next_url = (body.get("links") or {}).get("next")
        url = urljoin(base_url, next_url) if next_url else None
        params = None  # the next link already carries the query params
    return keys


def _object_records_incremental(
    subdomain: str,
    api_key: str,
    email_address: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[ZendeskSunshineResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Incremental object records: one `objects/query` walk per object type.

    The framework's declarative fan-out can't drive a POST body, so this mirrors its resume
    shape by hand: completed types are skipped, and the in-progress type resumes from its
    saved paginator snapshot.
    """
    base_url = get_base_url(subdomain)
    client_config = _client_config(subdomain, api_key, email_address)

    resume_state = _load_resume_state(resumable_source_manager) or {}
    # Pin the query window across retries: the pipeline advances the incremental watermark
    # per batch, so recomputing the window mid-job would skip history for types that hadn't
    # started syncing when the previous attempt died.
    window_start = (
        resume_state.get("window_start")
        or to_query_datetime(db_incremental_field_last_value)
        or DEFAULT_QUERY_WINDOW_START
    )
    completed: set[str] = set(resume_state.get("completed") or [])
    current_key = resume_state.get("current")
    current_child_state = resume_state.get("child_state")

    def save_checkpoint(current: Optional[str], child_state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(
            ZendeskSunshineResumeConfig(
                state={
                    "window_start": window_start,
                    "completed": sorted(completed),
                    "current": current,
                    "child_state": child_state,
                }
            )
        )

    for type_key in list_object_type_keys(subdomain, api_key, email_address):
        if type_key in completed:
            continue
        initial_paginator_state = current_child_state if type_key == current_key else None

        def child_resume_hook(paginator_state: Optional[dict[str, Any]], _key: str = type_key) -> None:
            save_checkpoint(_key, paginator_state)

        config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_query_resource(type_key, window_start, base_url)],
        }
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=child_resume_hook,
            initial_paginator_state=initial_paginator_state,
        )
        yield from resource

        completed.add(type_key)
        save_checkpoint(None, None)


def zendesk_sunshine_source(
    subdomain: str,
    api_key: str,
    email_address: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZendeskSunshineResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = ZENDESK_SUNSHINE_ENDPOINTS[endpoint]
    base_url = get_base_url(subdomain)
    items: Callable[[], Iterable[Any]]

    if endpoint_config.name == "object_records" and should_use_incremental_field:

        def incremental_items() -> Iterator[list[dict[str, Any]]]:
            return _object_records_incremental(
                subdomain,
                api_key,
                email_address,
                team_id,
                job_id,
                db_incremental_field_last_value,
                resumable_source_manager,
            )

        items = incremental_items
    elif endpoint_config.fanout_parent is not None:
        parent_config = ZENDESK_SUNSHINE_ENDPOINTS[endpoint_config.fanout_parent]
        config: RESTAPIConfig = {
            "client": _client_config(subdomain, api_key, email_address),
            "resource_defaults": {},
            "resources": _fanout_resources(endpoint_config, parent_config, base_url),
        }
        resources = rest_api_resources(
            config,
            team_id,
            job_id,
            None,
            resume_hook=_make_resume_hook(resumable_source_manager),
            initial_paginator_state=_load_resume_state(resumable_source_manager),
        )
        child = next(r for r in resources if r.name == endpoint_config.name)
        dependent_resource = child.add_map(
            rename_parent_fields(parent_config.name, endpoint_config.parent_field_renames)
        )
        items = lambda: dependent_resource  # noqa: E731
    else:
        top_level_config: RESTAPIConfig = {
            "client": _client_config(subdomain, api_key, email_address),
            "resource_defaults": {},
            "resources": [_top_level_resource(endpoint_config, base_url)],
        }
        resource = rest_api_resource(
            top_level_config,
            team_id,
            job_id,
            None,
            resume_hook=_make_resume_hook(resumable_source_manager),
            initial_paginator_state=_load_resume_state(resumable_source_manager),
        )
        items = lambda: resource  # noqa: E731

    response = SourceResponse(
        name=endpoint_config.name,
        items=items,
        primary_keys=list(endpoint_config.primary_keys),
        sort_mode="asc",
    )
    if endpoint_config.partition_key:
        response.partition_count = 1
        response.partition_size = 1
        response.partition_mode = "datetime"
        response.partition_format = "week"
        response.partition_keys = [endpoint_config.partition_key]
    return response


def validate_credentials(subdomain: str, api_key: str, email_address: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,), headers={"Accept": "application/json"})
    response = session.get(
        urljoin(get_base_url(subdomain), "objects/types"),
        params={"per_page": 1},
        auth=(f"{email_address}/token", api_key),
        timeout=30,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, (
            "Zendesk rejected the credentials. Check the subdomain, email address, and API token are correct, "
            "and that token access is enabled for your account."
        )
    if response.status_code in (403, 404):
        return False, (
            "The Zendesk Sunshine (legacy custom objects) API is not available for this account. "
            "Check that legacy custom objects are activated in Admin Center and that your plan supports them."
        )
    return False, f"Zendesk Sunshine returned an unexpected response (HTTP {response.status_code})"
