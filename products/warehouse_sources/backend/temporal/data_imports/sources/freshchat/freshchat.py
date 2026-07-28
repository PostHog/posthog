import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    FRESHCHAT_ENDPOINTS,
    PER_PAGE,
    PRIMARY_KEYS,
    FreshchatEndpointConfig,
)

VALIDATE_TIMEOUT = 10

# All documented Freshchat API hosts live under these Freshworks-owned domains: account
# subdomains and regional hosts (api.freshchat.com, api.eu.freshchat.com, ...) under
# freshchat.com, Freshsales Suite accounts under myfreshworks.com.
ALLOWED_HOST_SUFFIXES = ("freshchat.com", "myfreshworks.com")

HOST_NOT_ALLOWED_ERROR = "Freshchat domain is not allowed"


class FreshchatHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class FreshchatResumeConfig:
    # The next page number to fetch. Freshchat uses page/items_per_page pagination, so a single
    # integer is enough to pick back up. Endpoints are full refresh (no time window), so re-entering
    # a page and deduping on the primary key is safe.
    page: int


def normalize_domain(domain: str) -> str:
    """Normalize the Freshchat host the user supplied.

    Accepts a bare account name ("acme" -> "acme.freshchat.com"), a full host
    ("acme.freshchat.com", "acme.myfreshworks.com", "api.eu.freshchat.com"), or a URL with a
    scheme/path. Freshchat's base host varies by account and data center, so we keep whatever
    host the user gives and only default the domain when they pass a bare account name.
    """
    d = domain.strip().lower().removeprefix("https://").removeprefix("http://")
    d = d.split("/")[0].strip().rstrip("/")
    if "." not in d:
        d = f"{d}.freshchat.com"
    return d


def is_allowed_host(host: str) -> bool:
    """Only Freshworks-owned hosts are reachable: account subdomains and regional API hosts live
    under freshchat.com, Freshsales Suite accounts under myfreshworks.com. The domain is fully
    customer-controlled, so anything else (e.g. an internal hostname) is refused — the stored
    token plus scheduled syncs would otherwise let a user aim authenticated GETs at arbitrary
    hosts (SSRF)."""
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES)


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}/v2"


def build_base_params(config: FreshchatEndpointConfig) -> dict[str, Any]:
    """Query params shared across every page of one sync (everything except `page`)."""
    params: dict[str, Any] = {}
    if config.paginated:
        params["items_per_page"] = str(PER_PAGE)
        # Explicit stable sort so page boundaries don't skip/duplicate rows if the API's implicit
        # default order shifts while we page.
        params["sort_order"] = "asc"
    params.update(config.extra_params)
    return params


def _paginator_for(config: FreshchatEndpointConfig) -> BasePaginator:
    if not config.paginated:
        # Single-object endpoints (accounts/configuration) are one request, no pagination params.
        return SinglePagePaginator()
    # Freshchat pages by 1-based page number and reports the page count under
    # ``pagination.total_pages``; the paginator stops right after the last page (no extra empty
    # request) and is resumable by page number. When the count is absent it falls back to stopping
    # on the first empty page.
    return PageNumberPaginator(base_page=1, page=1, page_param="page", total_path="pagination.total_pages")


def freshchat_source(
    api_key: str,
    domain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshchatResumeConfig],
) -> SourceResponse:
    config = FRESHCHAT_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) so an edited or previously-saved domain
    # can't aim the stored token at a non-Freshworks host (SSRF). The base host is implicitly
    # trusted by the client's allowlist, so this suffix check on the domain itself is the real
    # boundary.
    normalized = normalize_domain(domain)
    if not is_allowed_host(normalized):
        raise FreshchatHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(domain),
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and error messages; only the non-secret Accept header is set here so the API
            # returns JSON rather than an HTML error page.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _paginator_for(config),
            # Pin every request (including any paginator/resume URL) to the account host and reject
            # redirects — a 3xx from the allowed host could otherwise carry the token off-host (SSRF).
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": build_base_params(config),
                    # Freshchat wraps list rows (and the single configuration object) under a
                    # resource key; the extractor unwraps a single matched object into one row.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(FreshchatResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Freshchat endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        # All endpoints are full refresh; we page with an explicit ascending sort.
        sort_mode="asc",
    )


def validate_credentials(domain: str, api_key: str) -> Optional[int]:
    """Probe the Freshchat API. Returns the HTTP status code, or ``None`` on a connection error.

    Hits the account-configuration endpoint — the cheapest resource any valid token can read.
    """
    _ok, status = validate_via_probe(
        # Redirects pinned off on the session so a 3xx can't carry the token to another host.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{_base_url(domain)}/accounts/configuration",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=VALIDATE_TIMEOUT,
    )
    return status
