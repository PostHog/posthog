from typing import Any, Optional

from requests import PreparedRequest, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.settings import (
    DEFAULT_PAGE_SIZE,
    KICKSCALE_BASE_URL,
    KICKSCALE_ENDPOINTS,
)


@frozen
class KickscaleResumeConfig:
    page: int


class KickscaleAuth(AuthConfigBase):
    """Kickscale requires two static headers together; either alone is rejected.

    The generic auth types each carry a single credential header, so both are set here and both
    reported as secret so the tracked session masks them wherever they surface in logs or
    captured samples.
    """

    def __init__(self, api_key: str, client_id: str) -> None:
        self.api_key = api_key
        self.client_id = client_id

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["api-key"] = self.api_key
        request.headers["client-id"] = self.client_id
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.api_key, self.client_id) if value)


class KickscalePageNumberPaginator(PageNumberPaginator):
    """Kickscale's list responses carry no total-count field, so a full-strength page is the
    only signal there's more to fetch; a short (or empty) page ends the sync."""

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=0, page_param="page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False

    def __str__(self) -> str:
        return f"KickscalePageNumberPaginator(page={self.page}, page_size={self._page_size})"


def _format_kickscale_datetime(value: Any) -> str:
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _incremental_window(cursor_path: str) -> IncrementalConfig:
    # `startDate` returns meetings/calls on or after the given instant, and `sortingOrder`
    # (set in get_resource) is pinned to ascending so rows arrive in cursor order for the
    # pipeline's watermark checkpoint.
    return {
        "cursor_path": cursor_path,
        "start_param": "startDate",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_kickscale_datetime,
    }


def _client_config(api_key: str, client_id: str) -> ClientConfig:
    return {
        "base_url": KICKSCALE_BASE_URL,
        "auth": KickscaleAuth(api_key=api_key, client_id=client_id),
        "paginator": KickscalePageNumberPaginator(page_size=DEFAULT_PAGE_SIZE),
        # Pin every request (and the api-key/client-id headers) to the Kickscale host and refuse
        # to follow a 3xx, so a server-side redirect can never replay the credentials off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    config = KICKSCALE_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {
            "pageSize": DEFAULT_PAGE_SIZE,
            "sortingOrder": "ascending",
            # Without `expand`, the embedded user profile and transcript are omitted from
            # every row.
            "expand": "user_client_augmentation,meeting_transcript",
            # `scopes` defaults to "external" only, silently dropping internal meetings from
            # every list response unless "internal" is requested alongside it.
            "scopes": "internal,external",
        },
    }

    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    if use_incremental:
        endpoint_config["incremental"] = _incremental_window(
            incremental_field_name or config.incremental_fields[0]["field"]
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def kickscale_source(
    api_key: str,
    client_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KickscaleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = KICKSCALE_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": _client_config(api_key, client_id),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(KickscaleResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_key,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Meetings/calls carry full transcripts once expanded, so rows can be large — keep
        # chunks smaller than the pipeline default to bound peak memory.
        chunk_size=1000,
        chunk_size_bytes=100 * 1024 * 1024,
    )


def validate_credentials(api_key: str, client_id: str) -> tuple[bool, str | None]:
    response = make_tracked_session(redact_values=(api_key, client_id), allow_redirects=False).get(
        f"{KICKSCALE_BASE_URL}/meetings",
        headers={"api-key": api_key, "client-id": client_id},
        params={"page": 0, "pageSize": 1},
        timeout=10,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code == 403:
        return (
            False,
            "Kickscale rejected the API key and client ID. Check both values under "
            "Settings > Integrations > API & Webhooks and reconnect.",
        )
    return False, f"Kickscale API returned an unexpected status code: {response.status_code}"
