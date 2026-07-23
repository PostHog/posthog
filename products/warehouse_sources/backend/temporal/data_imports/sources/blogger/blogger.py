import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.settings import BLOGGER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BLOGGER_BASE_URL = "https://www.googleapis.com/blogger/v3"
# Blogger caps `maxResults` per resource; 100 is comfortably within the limits for posts/comments/pages.
DEFAULT_PAGE_SIZE = 100


@dataclasses.dataclass
class BloggerResumeConfig:
    # Blogger paginates with an opaque `pageToken`; persisting it lets a heartbeat-timed-out sync pick
    # back up at the next page instead of restarting the endpoint.
    page_token: str | None = None


def _format_rfc3339(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp, which Blogger's date filters require."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class BloggerPageTokenPaginator(JSONResponseCursorPaginator):
    """Blogger's opaque `pageToken` cursor, with one twist: never checkpoint an empty page. An empty
    page yields no rows, so persisting its continuation token would let a crash skip past pages we
    never surfaced — re-walking the (cheap) empty pages on resume is the safe choice."""

    def __init__(self) -> None:
        super().__init__(cursor_path="nextPageToken", cursor_param="pageToken")
        self._last_page_had_items = True

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        self._last_page_had_items = bool(data)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._last_page_had_items:
            return None
        return super().get_resume_state()


def _make_sanitized_session(api_key: str) -> requests.Session:
    """Tracked session that strips the query string from the final response URL. Blogger carries the
    API key in `?key=...`, and both `raise_for_status()` and the client's retryable-error messages
    embed `response.url` — which the shared non-retryable error handler logs and surfaces. Stripping
    the query keeps the stable `.../blogger/v3` prefix that `BloggerSource.get_non_retryable_errors()`
    matches on, so error classification is unaffected while the key never leaks."""
    session = make_tracked_session(redact_values=(api_key,))
    original_send = session.send

    def send_with_sanitized_url(request: Any, **kwargs: Any) -> requests.Response:
        response = original_send(request, **kwargs)
        if response.url:
            response.url = urlsplit(response.url)._replace(query="").geturl()
        return response

    session.send = send_with_sanitized_url  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    return session


def validate_credentials(api_key: str, blog_id: str) -> tuple[bool, str | None]:
    """Probe `blogs.get` for the configured blog. This confirms both the API key and that the key can
    read the target blog in a single cheap request."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BLOGGER_BASE_URL}/blogs/{blog_id}",
        headers={"Accept": "application/json"},
        auth=APIKeyAuth(api_key=api_key, name="key", location="query"),
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the Blogger API. Please try again."
    if status in (400, 401, 403):
        return False, "Your Blogger API key is invalid or does not have access to this blog."
    if status == 404:
        return False, "No Blogger blog was found for that blog ID."
    return False, f"The Blogger API returned an unexpected error (status {status})."


def blogger_source(
    api_key: str,
    blog_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BloggerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BLOGGER_ENDPOINTS[endpoint]

    endpoint_def: Endpoint
    if config.is_single_object:
        # `blogs.get` returns a single blog object rather than a paginated `items` list.
        endpoint_def = {
            "path": config.path.format(blog_id=blog_id),
            "data_selector": "$",
            "paginator": SinglePagePaginator(),
        }
    else:
        params: dict[str, Any] = {"maxResults": DEFAULT_PAGE_SIZE}
        if config.order_by:
            params["orderBy"] = config.order_by
        # A body without `items` is a legit zero-row page (Blogger omits the key when empty), so the
        # selector is deliberately not required.
        endpoint_def = {
            "path": config.path.format(blog_id=blog_id),
            "params": params,
            "data_selector": "items",
            "paginator": BloggerPageTokenPaginator(),
        }
        # `startDate` is the only server-side filter Blogger offers; map the user's incremental cursor
        # (always `published`) onto it. On first sync there's no last value, so we pull full history.
        if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
            endpoint_def["incremental"] = {
                "start_param": "startDate",
                "cursor_path": "published",
                "convert": _format_rfc3339,
            }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BLOGGER_BASE_URL,
            "headers": {"Accept": "application/json"},
            # The Google API key always rides as the `key` query param (Blogger has no header form).
            "auth": {"type": "api_key", "name": "key", "api_key": api_key, "location": "query"},
            "session": _make_sanitized_session(api_key),
        },
        "resource_defaults": {},
        "resources": [{"name": endpoint, "endpoint": endpoint_def}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_token:
            initial_paginator_state = {"cursor": resume.page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint fires AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(BloggerResumeConfig(page_token=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Blogger only returns list results newest-first (its sort-direction param is unavailable), so
        # incremental endpoints scroll descending. Full-refresh endpoints don't care about order.
        sort_mode="desc" if config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
