from typing import Any
from urllib.parse import quote

from requests import Request, Response

from products.warehouse_sources.sources.sdk import (
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.shortio.settings import SHORTIO_ENDPOINTS

SHORTIO_BASE_URL = "https://api.short.io"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to the domain list.
DEFAULT_PROBE_PATH = "/api/domains"


def _auth_headers(api_key: str) -> dict[str, str]:
    # Short.io expects the raw secret API key in the Authorization header — no `Bearer` prefix.
    return {"Authorization": api_key, "Accept": "application/json"}


@frozen
class ShortioResumeConfig:
    paginator_state: dict[str, Any]


class StatisticsPaginator(SinglePagePaginator):
    def init_request(self, request: Request) -> None:
        # Dependent REST resources do not forward endpoint.json to the child request.
        request.json = {"period": "total", "tz": "UTC", "clicksChartInterval": "day"}


class LastClicksPaginator(StatisticsPaginator):
    def __init__(self) -> None:
        super().__init__()
        self.before_date: str | None = None
        self.limit = 30

    def init_request(self, request: Request) -> None:
        request.json = {"period": "total", "tz": "UTC"}
        self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not data:
            self._has_next_page = False
            return
        full_page = len(data) >= self.limit
        if self.before_date is not None:
            if any(row["dt"] > self.before_date for row in data):
                raise ValueError("Short.io click pagination did not advance")
            # An inclusive boundary can repeat the complete timestamp group already yielded.
            data[:] = [row for row in data if row["dt"] < self.before_date]
        if not data:
            if full_page:
                self._expand_page(data)
            else:
                self._has_next_page = False
            return
        before_date = min(row["dt"] for row in data)
        if full_page:
            # Keep the oldest timestamp for the next request because this page may split its clicks.
            complete_rows = [row for row in data if row["dt"] > before_date]
            if not complete_rows:
                self._expand_page(data)
                return
            data[:] = complete_rows
            before_date = min(row["dt"] for row in data)
        self.before_date = before_date
        self.limit = 30

    def _expand_page(self, data: list[Any]) -> None:
        # Bound memory use and fail instead of dropping an oversized timestamp group.
        if self.limit >= 10000:
            raise ValueError("Short.io returned too many clicks at one timestamp to paginate safely")
        self.limit = min(self.limit * 2, 10000)
        data.clear()

    def update_request(self, request: Request) -> None:
        request.json = {**(request.json or {}), "limit": self.limit}
        if self.before_date is not None:
            request.json = {**(request.json or {}), "beforeDate": self.before_date}

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"before_date": self.before_date, "limit": self.limit} if self.has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self.before_date = state.get("before_date")
        self.limit = state.get("limit", 30)


class LinksBatchPaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="nextPageToken", cursor_param="pageToken", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        if data:
            # The child resolves one request per row, so expose each links page as one batch.
            data[:] = [{"api_id": quote(",".join(str(row["idString"]) for row in data), safe="")}]


def _link_row(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("password", None)
    row["domain_id"] = row.pop("_domains_id")
    return row


def _link_parent_row(row: dict[str, Any]) -> dict[str, Any]:
    row = _link_row(row)
    row["api_id"] = quote(str(row["idString"]), safe="")
    return row


def _click_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    domain_id = row.pop("_links_domain_id")
    if any(not isinstance(clicks, int | float) or isinstance(clicks, bool) for clicks in row.values()):
        raise ValueError("Short.io returned an invalid link click count")
    return [{"domain_id": domain_id, "link_id": link_id, "clicks": clicks} for link_id, clicks in row.items()]


def _interval_row(row: dict[str, Any]) -> dict[str, Any]:
    row["domain_id"] = row.pop("_links_domain_id")
    row["link_id"] = row.pop("_links_idString")
    return row


def _last_click_row(row: dict[str, Any]) -> dict[str, Any]:
    row["domain_id"] = row.pop("_domains_id")
    return row


def _resources(endpoint: str) -> list[EndpointResource]:
    resources: list[EndpointResource] = [
        {"name": "domains", "endpoint": {"path": "/api/domains", "data_selector_required": True}}
    ]
    if endpoint == "domains":
        return resources
    if endpoint == "last_clicks":
        resources.append(
            {
                "name": endpoint,
                "endpoint": {
                    "path": SHORTIO_ENDPOINTS[endpoint].path,
                    "method": "POST",
                    "params": {"domain_id": {"type": "resolve", "resource": "domains", "field": "id"}},
                    "paginator": LastClicksPaginator(),
                    "data_selector_required": True,
                },
                "include_from_parent": ["id"],
                "data_map": _last_click_row,
            }
        )
        return resources

    resources.append(
        {
            "name": "links",
            "endpoint": {
                "path": SHORTIO_ENDPOINTS["links"].path,
                "params": {
                    "domain_id": {"type": "resolve", "resource": "domains", "field": "id"},
                    "limit": 150,
                },
                "data_selector": "links",
                "data_selector_required": True,
                "paginator": LinksBatchPaginator()
                if endpoint == "link_clicks"
                else JSONResponseCursorPaginator(
                    cursor_path="nextPageToken", cursor_param="pageToken", raise_on_repeated_cursor=True
                ),
            },
            "include_from_parent": ["id"],
            "data_map": _link_row if endpoint in ("links", "link_clicks") else _link_parent_row,
        }
    )
    if endpoint == "links":
        return resources

    stats_params: dict[str, Any] = {
        "link_id": {"type": "resolve", "resource": "links", "field": "api_id"},
    }
    stats_endpoint: Endpoint = {
        "path": SHORTIO_ENDPOINTS[endpoint].path,
        "params": stats_params,
        "paginator": SinglePagePaginator(),
        "data_selector": "$",
    }
    resource: EndpointResource = {
        "name": endpoint,
        "endpoint": stats_endpoint,
        "include_from_parent": ["domain_id"],
        "data_map": _click_rows,
    }
    if endpoint == "link_clicks":
        stats_params["domain_id"] = {"type": "resolve", "resource": "links", "field": "domain_id"}
    else:
        stats_endpoint.update(
            {
                "method": "POST",
                "data_selector": "clickStatistics",
                "data_selector_required": True,
                "paginator": StatisticsPaginator(),
            }
        )
        resource["include_from_parent"] = ["domain_id", "idString"]
        resource["data_map"] = _interval_row
    resources.append(resource)
    return resources


def shortio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShortioResumeConfig],
) -> SourceResponse:
    config = SHORTIO_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHORTIO_BASE_URL,
            # Only the non-secret Accept header is set here; the raw key rides in Authorization via
            # the framework auth config so its value is redacted from logs and error messages.
            "headers": {"Accept": "application/json"},
            # Short.io expects the raw secret key in Authorization — no `Bearer` prefix.
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            # The domain list has no pagination, so a single request returns the whole collection.
            "paginator": SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": [*_resources(endpoint)],
    }

    state = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_state(paginator_state: dict[str, Any] | None) -> None:
        if paginator_state is not None:
            resumable_source_manager.save_state(ShortioResumeConfig(paginator_state=paginator_state))

    resource = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_state,
        initial_paginator_state=state.paginator_state if state else None,
    )[-1]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
        on_complete=resumable_source_manager.clear_state,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SHORTIO_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers=_auth_headers(api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Short.io API key"
    if status is None:
        return False, "Could not connect to Short.io. Please try again."
    return False, f"Short.io returned HTTP {status}"
