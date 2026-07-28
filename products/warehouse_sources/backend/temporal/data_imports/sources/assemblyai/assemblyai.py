import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import ASSEMBLYAI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# AssemblyAI offers a US base URL and an EU data-residency variant. The Authorization header is the
# raw API key (no "Bearer" prefix).
BASE_URLS: dict[str, str] = {
    "us": "https://api.assemblyai.com",
    "eu": "https://api.eu.assemblyai.com",
}
DEFAULT_REGION = "us"

# List endpoint max page size is 200.
PAGE_SIZE = 200


@dataclasses.dataclass
class AssemblyAIResumeConfig:
    # Absolute URL of the next list page to fetch (from page_details.next_url). Following it walks
    # newest-to-oldest through the transcript list via the API's before_id cursor.
    next_url: str | None = None


def base_url_for_region(region: str | None) -> str:
    return BASE_URLS.get((region or DEFAULT_REGION).lower(), BASE_URLS[DEFAULT_REGION])


def _pinned_url(base_url: str, url: str) -> str:
    """Resolve a page_details URL (absolute or relative) and pin it to the selected base host.

    next_url comes from the API response body (and is persisted in resume state), so a tampered
    response must not be able to redirect the credential-bearing request to another host. Anything
    that resolves off the selected base origin is rejected.
    """
    resolved = url if url.startswith(("http://", "https://")) else urljoin(base_url, url)
    base, target = urlsplit(base_url), urlsplit(resolved)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"AssemblyAI pagination URL {resolved!r} is not on the selected host {base_url!r}")
    return resolved


class AssemblyAINextUrlPaginator(JSONResponsePaginator):
    """Follows page_details.next_url, pinned to the selected regional host.

    Also stops as soon as a page carries no items — the transcript list is finite and
    newest-first, so an empty page means the walk is done regardless of any next_url.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(next_url_path="page_details.next_url")
        self._base_url = base_url

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None:
            self._next_url = _pinned_url(self._base_url, self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if self._next_url is not None:
            # Persisted state is still untrusted input — pin it to the selected host before fetching.
            self._next_url = _pinned_url(self._base_url, self._next_url)


def validate_credentials(api_key: str, region: str | None) -> bool:
    # Cheapest probe that exercises the token: list a single transcript.
    base_url = base_url_for_region(region)
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url}/v2/transcript?limit=1",
        headers={"Authorization": api_key, "Accept": "application/json"},
    )
    return ok


def _hydrate_transcript(client: RESTClient, transcript_id: str) -> dict[str, Any]:
    """Fetch the full transcript object for a single id (the list rows are summaries)."""
    for page in client.paginate(path=f"/v2/transcript/{transcript_id}", paginator=SinglePagePaginator()):
        if page:
            return page[0]
    raise ValueError(f"AssemblyAI returned an empty body for transcript {transcript_id}")


def assemblyai_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AssemblyAIResumeConfig],
) -> SourceResponse:
    config = ASSEMBLYAI_ENDPOINTS[endpoint]
    base_url = base_url_for_region(region)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "headers": {"Accept": "application/json"},
            # AssemblyAI expects the raw API key in Authorization (no "Bearer" prefix).
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            "paginator": AssemblyAINextUrlPaginator(base_url),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": endpoint,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the just-finished page (merge dedupes) rather than skipping it. Resume picks up
        # at the saved next page — earlier list pages are never re-fetched.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(AssemblyAIResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # full refresh only — no server-side watermark filter exists (see settings.py)
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        if not config.hydrate:
            yield from resource
            return
        # One client (and session) reused for every hydration request so urllib3 keeps the
        # connection alive instead of re-handshaking per transcript.
        hydration_client = RESTClient(
            base_url=base_url,
            headers={"Accept": "application/json"},
            auth=APIKeyAuth(api_key=api_key, name="Authorization", location="header"),
        )
        for page in resource:
            yield [_hydrate_transcript(hydration_client, item["id"]) for item in page]

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The list endpoint returns transcripts newest-first and exposes no ascending sort, so rows
        # arrive in descending creation order. Full refresh only, so this never drives a watermark.
        sort_mode="desc",
    )
