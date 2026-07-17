import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import (
    MUX_ENDPOINTS,
    MuxEndpointConfig,
)

MUX_BASE_URL = "https://api.mux.com"
# Endpoint used to confirm a token is genuine when no specific schema is being validated.
DEFAULT_VALIDATION_PATH = "/video/v1/assets"


@dataclasses.dataclass
class MuxResumeConfig:
    # Next offset page to fetch (offset/limit pagination). None for cursor-paginated endpoints.
    page: int | None = None
    # Next `next_cursor` value to fetch (cursor pagination, List Assets only).
    cursor: str | None = None


class MuxPagePaginator(BasePaginator):
    """Page-number pagination that stops on the first short (or empty) page.

    Mux's offset list endpoints return a full ``limit``-sized page while more rows remain, so a page
    shorter than ``limit`` (including an empty one) means the collection is exhausted. The built-in
    ``PageNumberPaginator`` only stops on an *empty* page, which would issue one extra request per
    endpoint — this preserves the short-page termination the hand-rolled source relied on. Resumable
    via the next page number.
    """

    def __init__(self, page_size: int, page_param: str = "page", page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page_param = page_param
        self.page = page

    def _inject_page(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._inject_page(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data or len(data) < self.page_size:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_page(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"MuxPagePaginator(page={self.page})"


def _make_session(access_token_id: str, secret_key: str) -> requests.Session:
    # Mux authenticates with HTTP Basic auth (Access Token ID as username, Secret as password).
    # Redact the secret wherever it might surface in tracked logs/samples.
    session = make_tracked_session(redact_values=(secret_key,))
    session.auth = (access_token_id, secret_key)
    return session


def get_validation_status(access_token_id: str, secret_key: str, path: str) -> int | None:
    """Probe a list endpoint and return the HTTP status code, or None on a transport error."""
    url = f"{MUX_BASE_URL}{path}?{urlencode({'limit': 1})}"
    _ok, status = validate_via_probe(
        lambda: _make_session(access_token_id, secret_key),
        url,
    )
    return status


def _strip_sensitive_fields(item: dict[str, Any], config: MuxEndpointConfig) -> dict[str, Any]:
    """Drop credential-bearing fields before the row is batched into the warehouse.

    Mux list responses embed live-stream ingest keys (`stream_key`) and direct-upload PUT URLs
    (`url`). Persisting them would expose a valid broadcast/upload credential to anyone who can
    query the imported table, crossing from analytics-read to write access in the customer's Mux
    account, so we remove them rather than import them. Live-stream simulcast targets carry their
    own per-destination `stream_key`, so those are stripped too.
    """
    if not config.sensitive_fields:
        return item
    cleaned = {k: v for k, v in item.items() if k not in config.sensitive_fields}
    targets = cleaned.get("simulcast_targets")
    if isinstance(targets, list):
        cleaned["simulcast_targets"] = [
            {k: v for k, v in target.items() if k != "stream_key"} if isinstance(target, dict) else target
            for target in targets
        ]
    return cleaned


def _normalize_row(item: dict[str, Any], config: MuxEndpointConfig) -> dict[str, Any]:
    """Coerce the partition timestamp to an int so datetime partitioning can parse it.

    Mux returns `created_at` as a string-encoded Unix timestamp in seconds (e.g. "1609869152").
    The pipeline's datetime partitioner parses ints via `fromtimestamp` but would misparse the raw
    string, so convert it where it's the partition key.
    """
    if config.partition_key == "created_at":
        created_at = item.get("created_at")
        if isinstance(created_at, str) and created_at.isdigit():
            return {**item, "created_at": int(created_at)}
    return item


def mux_source(
    access_token_id: str,
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MuxResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MUX_ENDPOINTS[endpoint]

    paginator: BasePaginator
    if config.use_cursor:
        # List Assets returns `next_cursor` in the body; a null/absent value ends pagination.
        paginator = JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
    else:
        paginator = MuxPagePaginator(page_size=config.page_size)

    def _map_row(item: dict[str, Any]) -> dict[str, Any]:
        # Strip credential-bearing fields, then coerce the partition timestamp — same order as before.
        return _normalize_row(_strip_sensitive_fields(item, config), config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MUX_BASE_URL,
            # Basic auth via the framework so the secret is redacted from logs and raised errors.
            "auth": {"type": "http_basic", "username": access_token_id, "password": secret_key},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.page_size},
                    "data_selector": "data",
                },
                "data_map": _map_row,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.use_cursor:
                if resume.cursor is not None:
                    initial_paginator_state = {"cursor": resume.cursor}
            elif resume.page is not None:
                initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if config.use_cursor:
            cursor = state.get("cursor")
            if cursor is not None:
                resumable_source_manager.save_state(MuxResumeConfig(cursor=cursor))
        else:
            page = state.get("page")
            if page is not None:
                resumable_source_manager.save_state(MuxResumeConfig(page=int(page)))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
