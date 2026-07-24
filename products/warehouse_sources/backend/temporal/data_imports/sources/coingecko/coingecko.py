import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import COINGECKO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# Two distinct hosts: the free Demo plan (and keyless public access) live on api.coingecko.com,
# paid Pro plans on pro-api.coingecko.com. The plan also selects which API-key header to send.
DEMO_BASE_URL = "https://api.coingecko.com/api/v3"
PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"

PLAN_DEMO = "demo"
PLAN_PRO = "pro"

# /coins/markets allows up to 250 per page; other paginated endpoints accept it too.
PAGE_SIZE = 250
MAX_RETRY_ATTEMPTS = 6

# CoinGecko signals rate limiting via a 429 status (retried by the client on status alone) and, on the
# keyless/demo tier, via a 200/4xx body carrying ``{"status":{"error_code":429}}``. The client only
# retries on 429/5xx status, so classify that in-body envelope as retryable by content substring. Both
# whitespace variants are matched so the classification survives a compact- vs spaced-JSON server, the
# same way the old structural ``status.error_code == 429`` check was whitespace-agnostic.
RATE_LIMIT_BODY_MARKERS = ('"error_code":429', '"error_code": 429')


@dataclasses.dataclass
class CoinGeckoResumeConfig:
    # Next page to fetch for paginated endpoints. Unused for single-response reference endpoints.
    page: int = 1


def _base_url(plan: str) -> str:
    return PRO_BASE_URL if plan == PLAN_PRO else DEMO_BASE_URL


def _api_key_header(plan: str) -> str:
    return "x-cg-pro-api-key" if plan == PLAN_PRO else "x-cg-demo-api-key"


def _headers(plan: str, api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers[_api_key_header(plan)] = api_key
    return headers


class CoinGeckoPagePaginator(PageNumberPaginator):
    """CoinGecko paginates with ``page``/``per_page``. A short page (fewer than ``per_page`` items) or
    an empty page is the last one — stop without paying an extra empty-page request, since the free
    tier's tight rate limits make sparing that request worthwhile. Resume replays the last full page
    (merge dedupes on the primary key)."""

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def coingecko_source(
    plan: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = COINGECKO_ENDPOINTS[endpoint]

    params: dict[str, Any] = dict(config.extra_params)
    if config.paginated:
        params["per_page"] = PAGE_SIZE

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(plan),
            # Only non-secret headers here; the API key rides in the framework auth config below so
            # its value is redacted from logs and raised error messages.
            "headers": {"Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": _api_key_header(plan),
                "location": "header",
            },
            "max_retries": MAX_RETRY_ATTEMPTS,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Bare-array bodies. A non-list body means the response shape changed (or an
                    # unexpected error envelope) — fail loud rather than syncing a garbage row.
                    "data_selector_required": True,
                    "paginator": CoinGeckoPagePaginator(PAGE_SIZE) if config.paginated else SinglePagePaginator(),
                    # The keyless/demo tier reports rate limiting inside a success-status body; the
                    # client retries on status only, so promote that in-body signal to a retry.
                    "response_actions": [{"content": marker, "action": "retry"} for marker in RATE_LIMIT_BODY_MARKERS],
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(CoinGeckoResumeConfig(page=int(state["page"])))

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
        # Snapshot/reference endpoints expose no stable created_at, so there's nothing to partition on.
        partition_count=None,
        partition_size=None,
        column_hints=resource.column_hints,
    )


def validate_credentials(plan: str, api_key: str) -> bool:
    """Confirm the key is genuine by pinging with the plan's auth header. A valid key returns 200;
    an invalid one returns 401. Transient/network failures also map to False (not validated)."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,) if api_key else ()),
        f"{_base_url(plan)}/ping",
        headers=_headers(plan, api_key),
    )
    return ok
