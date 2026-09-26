import dataclasses
from typing import Any, Optional
from urllib.parse import urlsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.settings import FOLK_BASE_URL, FOLK_ENDPOINTS

# Documented maximum on every list endpoint (the default is 20).
FOLK_PAGE_SIZE = 100


class FolkUntrustedURLError(Exception):
    pass


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Folk API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `pagination.nextLink` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/v1/`
    path prefix keeps a poisoned resume state or a hostile upstream response from retargeting the
    request at another host and leaking the token (SSRF). Returns the URL unchanged when trusted.
    """
    parts = urlsplit(url)
    is_trusted = parts.scheme == "https" and parts.netloc == "api.folk.app" and parts.path.startswith("/v1/")
    if not is_trusted:
        raise FolkUntrustedURLError("Refusing to follow a pagination URL outside the Folk API")
    return url


class FolkPaginator(JSONResponsePaginator):
    """Follows the envelope's `data.pagination.nextLink` URL, refusing any URL off the Folk API
    origin, whether it arrived in a response body or was seeded from saved resume state.

    The last page omits `nextLink` from the `pagination` object, which ends the walk."""

    def __init__(self) -> None:
        super().__init__(next_url_path="data.pagination.nextLink")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)


@dataclasses.dataclass(frozen=True)
class FolkResumeConfig:
    # Full next-page URL from the response's `data.pagination.nextLink` field (omitted on the last
    # page). It carries the opaque cursor and the limit, so following it resumes the walk exactly.
    next_url: str | None = None


def probe_credentials(api_key: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of the Folk API. Returns the HTTP status code, or None on a connection failure.

    Probes the given endpoint's own path when set (one row, to confirm access to that resource),
    else `/v1/users/me`, the cheapest call that confirms the key is genuine."""
    config = FOLK_ENDPOINTS.get(endpoint) if endpoint else None
    url = f"{FOLK_BASE_URL}{config.path}?limit=1" if config else f"{FOLK_BASE_URL}/v1/users/me"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return status


def folk_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FolkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = schema_for_resource(FOLK_ENDPOINTS, endpoint)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FOLK_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            "paginator": FolkPaginator(),
        },
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": FOLK_PAGE_SIZE},
                    "data_selector": "data.items",
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint lands AFTER a page is yielded so a
        # crash re-yields the last page (full refresh rewrites the table, so no duplicates land).
        if state and state.get("next_url"):
            resumable_source_manager.save_state(FolkResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
