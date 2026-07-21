import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.settings import (
    DELIGHTED_ENDPOINTS,
    DelightedEndpointConfig,
)

DELIGHTED_HOST = "api.delighted.com"
DELIGHTED_BASE_URL = f"https://{DELIGHTED_HOST}/v1"
# Delighted caps list pages at 100 items.
PAGE_SIZE = 100


@dataclasses.dataclass
class DelightedResumeConfig:
    next_url: str


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for Delighted's time filters.

    Delighted stores and filters timestamps as epoch seconds, so the persisted watermark is
    already an int in the common case; datetimes are accepted defensively.
    """
    if value is None:
        return None
    if isinstance(value, bool):
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
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_params(
    config: DelightedEndpointConfig,
    incremental_field: Optional[str],
    since_value: Optional[int],
) -> dict[str, Any]:
    if config.pagination == "none":
        return {}

    params: dict[str, Any] = {"per_page": PAGE_SIZE, **config.extra_params}

    # Ascending order on the cursor field keeps already-fetched pages stable and lets the
    # incremental watermark advance monotonically. Only survey_responses documents an
    # `order` param; the other list endpoints return oldest-first by default.
    order = config.default_order
    if incremental_field is not None:
        order = config.order_param_map.get(incremental_field, order)
    if order is not None:
        params["order"] = order

    if since_value is not None and incremental_field is not None:
        param_name = config.incremental_param_map.get(incremental_field)
        if param_name is not None:
            params[param_name] = since_value

    return params


def _next_page_url(url: str) -> str:
    """Return the same URL with its `page` query param incremented (default page is 1)."""
    scheme, netloc, path, query, fragment = urlsplit(url)
    query_params = {key: values[-1] for key, values in parse_qs(query).items()}
    current_page = int(query_params.get("page", "1"))
    query_params["page"] = str(current_page + 1)
    return urlunsplit((scheme, netloc, path, urlencode(query_params), fragment))


class DelightedPaginator(BasePaginator):
    """Reproduces Delighted's mixed list pagination.

    A server-provided RFC 5988 ``Link`` header ``rel="next"`` cursor takes priority (the
    ``people`` endpoint paginates this way). Otherwise page/per_page list endpoints advance by
    incrementing the ``page`` query param while a full page comes back; a short page ends the run.

    Off-host ``next`` links are not filtered here — the client's ``allowed_hosts`` pin rejects any
    request to a host other than the API host before it leaves the process, so a tampered link
    raises rather than forwarding the Authorization header off-host (SSRF).
    """

    def __init__(self, page_mode: bool, page_size: int) -> None:
        super().__init__()
        self.page_mode = page_mode
        self.page_size = page_size
        self._next_url: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume URL to the first request so a resumed run starts at the saved
        # next-page link rather than the base path.
        if self._next_url is not None:
            request.url = self._next_url
            request.params = {}

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        link_next = response.links.get("next", {}).get("url") if response.links else None
        if link_next:
            self._next_url = link_next
            self._has_next_page = True
            return

        # Page-number endpoints signal the end of results only by returning a short page, so a
        # final empty page may be fetched when the row count is an exact multiple of the page size.
        self._next_url = None
        if self.page_mode and data is not None and len(data) == self.page_size:
            self._next_url = _next_page_url(response.url)
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_url is not None:
            request.url = self._next_url
            # The next-page URL is self-contained; drop the original params so prepare_request
            # doesn't re-append them each page.
            request.params = {}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_url": self._next_url} if self._has_next_page and self._next_url is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            self._next_url = next_url
            self._has_next_page = True


def delighted_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DelightedResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = DELIGHTED_ENDPOINTS[endpoint]

    since_value = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None
    cursor_field = incremental_field if should_use_incremental_field else None
    params = _build_params(config, cursor_field, since_value)

    paginator: BasePaginator = (
        SinglePagePaginator()
        if config.pagination == "none"
        else DelightedPaginator(page_mode=config.pagination == "page", page_size=PAGE_SIZE)
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DELIGHTED_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Basic auth: the API key is the username, password is blank. Supplied via the framework
            # auth config so the credential participates in log redaction.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            # Pin every request (paginator next links and seeded resume URLs included) to the API
            # host, and refuse to follow redirects: a server-controlled next/redirect must never
            # carry the Authorization header to another origin (SSRF). Base host is implicitly
            # allowed, so an empty list means "the Delighted API host only".
            "allowed_hosts": [],
            "allow_redirects": False,
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.pagination != "none" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(DelightedResumeConfig(next_url=state["next_url"]))

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
        primary_keys=[config.primary_key] if config.primary_key else None,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid. /v1/metrics.json is a cheap authenticated probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{DELIGHTED_BASE_URL}/metrics.json",
        auth=HttpBasicAuth(username=api_key, password=""),
    )
    return ok
