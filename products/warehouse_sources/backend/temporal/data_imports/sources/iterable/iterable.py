import dataclasses
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import ITERABLE_ENDPOINTS

# Iterable is region-locked: a key issued in one data center only works against that data center.
ITERABLE_BASE_URLS: dict[str, str] = {
    "us": "https://api.iterable.com",
    "eu": "https://api.eu.iterable.com",
}

# Safety bound on the pagination loop. Iterable's list endpoints normally return everything in a
# single response, but if one ever starts returning `nextPageUrl` we don't want an unbounded scan.
MAX_PAGES = 10_000


@dataclasses.dataclass
class IterableResumeConfig:
    next_url: str


def base_url_for_region(region: str | None) -> str:
    return ITERABLE_BASE_URLS.get((region or "us").lower(), ITERABLE_BASE_URLS["us"])


def _probe_headers(api_key: str) -> dict[str, str]:
    # The Api-Key credential rides in a header the tracked session's name-based scrubber doesn't
    # know, so the probe session masks it by value via `redact_values`.
    return {"Api-Key": api_key, "Accept": "application/json"}


def validate_credentials(api_key: str, region: str | None) -> bool:
    # `/api/channels` is a cheap, low-cardinality endpoint that requires a valid server-side key.
    url = f"{base_url_for_region(region)}/api/channels"
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers=_probe_headers(api_key),
    )
    return ok


def _is_same_origin(base_url: str, url: str) -> bool:
    base = urlparse(base_url)
    target = urlparse(url)
    return (target.scheme, target.netloc) == (base.scheme, base.netloc)


def _resolve_next_url(base_url: str, next_page: Any) -> str | None:
    """Normalize the `nextPageUrl` value from a response body into an absolute URL.

    Absolute URLs are only followed when they point at the selected Iterable base URL.
    The session carries the `Api-Key` header, so a `nextPageUrl` aimed at another host
    (e.g. an attacker-controlled value echoed back in a response) would leak the key —
    such off-host pages stop pagination instead.
    """
    if not next_page or not isinstance(next_page, str):
        return None
    if next_page.startswith("http://") or next_page.startswith("https://"):
        return next_page if _is_same_origin(base_url, next_page) else None
    return f"{base_url}{next_page}" if next_page.startswith("/") else f"{base_url}/{next_page}"


class IterableNextPagePaginator(BaseNextUrlPaginator):
    """Follows Iterable's body-level ``nextPageUrl``.

    Iterable list endpoints normally return their whole result set in one response, but if one ever
    starts paging we resolve a relative ``nextPageUrl`` against the region base URL and refuse to
    follow an off-host absolute link. The session carries the ``Api-Key`` header, so an
    attacker-echoed off-host ``nextPageUrl`` would otherwise leak the key — such links stop
    pagination (the clean completion the hand-rolled source produced) rather than being followed.
    ``max_pages`` bounds the loop so a self-referential ``nextPageUrl`` can't scan unbounded.
    """

    def __init__(self, base_url: str, max_pages: int = MAX_PAGES) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_pages = max_pages
        self._pages = 0

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._pages += 1
        try:
            next_page = response.json().get("nextPageUrl")
        except Exception:
            next_page = None
        next_url = _resolve_next_url(self.base_url, next_page)
        if next_url is not None and self._pages < self.max_pages:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False


def iterable_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IterableResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ITERABLE_ENDPOINTS[endpoint]
    base_url = base_url_for_region(region)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Only the non-secret Accept header goes here; the Api-Key credential is supplied via the
            # framework auth config so its value is redacted from logs and sampled request captures.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "Api-Key", "location": "header"},
            "paginator": IterableNextPagePaginator(base_url),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # `.get(data_key, [])` in the hand-rolled source treated a missing key as zero
                    # rows, not an error — so the selector is NOT required (no fail-loud here).
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only resume from a same-origin URL. A resume URL pointing off-host (corrupted/poisoned
        # state) must not be requested with the Api-Key header — start from the top instead.
        if resume is not None and _is_same_origin(base_url, resume.next_url):
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(IterableResumeConfig(next_url=state["next_url"]))

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
        primary_keys=[config.primary_key],
    )
