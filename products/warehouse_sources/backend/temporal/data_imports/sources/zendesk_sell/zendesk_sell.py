"""Transport layer for the Zendesk Sell (Base CRM) Core API.

Zendesk Sell's Core API lives at https://api.getbase.com/v2/. It returns a uniform envelope
(`{"items": [{"data": {...}, "meta": {...}}], "meta": {"links": {"next_page": ...}}}`) and paginates
with a 1-based `page` parameter plus `per_page` (max 100). We follow `meta.links.next_page` verbatim
rather than constructing page URLs ourselves, as the API docs instruct — but only after validating
each URL is still pinned to the Zendesk Sell API origin, so a hostile response or poisoned resume
state can't retarget an authenticated request at another host (`_validate_pagination_url`).

Every endpoint is full refresh. The Core API supports `sort_by` ordering but exposes no server-side
`updated_after` / `since` timestamp filter on its list endpoints, so there is no way to fetch only
changed rows cheaply — an "incremental" sort-and-skip would still page through the entire history each
run. True change capture is only available via the separate, queue-based Sync API. We therefore ship
full refresh and leave incremental off until that can be verified against a live account.
"""

import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.settings import (
    ZENDESK_SELL_ENDPOINTS,
)

ZENDESK_SELL_BASE_URL = "https://api.getbase.com"
ZENDESK_SELL_HOST = "api.getbase.com"
ZENDESK_SELL_PATH_PREFIX = "/v2/"
PER_PAGE = 100


class ZendeskSellUntrustedURLError(Exception):
    """A pagination URL (resumed or upstream) pointed somewhere other than the Zendesk Sell API."""


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Zendesk Sell API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `meta.links.next_page` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/v2/` path
    prefix keeps a poisoned resume state or a hostile upstream response from retargeting the request at
    another host and leaking the token (SSRF). Returns the URL unchanged when it is trusted.
    """
    parts = urlsplit(url)
    is_trusted = (
        parts.scheme == "https"
        and parts.netloc == ZENDESK_SELL_HOST
        and parts.path.startswith(ZENDESK_SELL_PATH_PREFIX)
    )
    if not is_trusted:
        raise ZendeskSellUntrustedURLError(
            f"Refusing to follow pagination URL outside {ZENDESK_SELL_BASE_URL}{ZENDESK_SELL_PATH_PREFIX}"
        )
    return url


@dataclasses.dataclass
class ZendeskSellResumeConfig:
    # Full next-page URL returned by the API. None means "start the endpoint at its first page".
    next_url: str | None = None


class ZendeskSellNextPagePaginator(JSONResponsePaginator):
    """Follows `meta.links.next_page`, but pins every next/resume URL to the Zendesk Sell API origin.

    The framework's client-level host-pinning only compares hostnames; the hand-rolled source also
    rejected a same-host URL on the wrong scheme or outside the `/v2/` path prefix, so validate the
    extracted next link and any seeded resume URL here to preserve that stronger SSRF boundary. A
    poisoned or hostile URL raises before the bearer token is ever sent to it, and the failing page is
    neither yielded nor checkpointed.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="meta.links.next_page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None:
            _validate_pagination_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            _validate_pagination_url(next_url)
        super().set_resume_state(state)


def _extract_item_data(item: dict[str, Any]) -> dict[str, Any]:
    """Unwrap an envelope item's `data` object.

    Every item in the Zendesk Sell envelope carries a `data` object — direct access fails fast on a
    malformed response rather than silently dropping records.
    """
    return item["data"]


def zendesk_sell_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZendeskSellResumeConfig],
) -> SourceResponse:
    config = ZENDESK_SELL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ZENDESK_SELL_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so the token is redacted from logged
            # URLs, captured samples, and raised error messages; only the non-secret Accept header here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": access_token},
            "paginator": ZendeskSellNextPagePaginator(),
            # `allow_redirects=False` stops a redirect response from sending the bearer token to another
            # host; the paginator already pins every next/resume URL to the API origin.
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PER_PAGE},
                    # The envelope wraps every row under `items[*].data`; select the item list, then
                    # unwrap `data` per item (via `data_map` below) so a missing `data` key fails loud
                    # (KeyError) instead of silently dropping the record. Missing/empty `items` is a
                    # legit zero-row page.
                    "data_selector": "items",
                },
                "data_map": _extract_item_data,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(ZendeskSellResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Zendesk Sell endpoint is full refresh
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


def validate_credentials(access_token: str) -> bool:
    """Cheap probe that the access token is genuine: list a single contact."""
    url = f"{ZENDESK_SELL_BASE_URL}/v2/contacts?{urlencode({'per_page': 1})}"
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,), allow_redirects=False),
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    return ok
