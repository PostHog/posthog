import re
import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse

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
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import KUSTOMER_ENDPOINTS

# Kustomer list pages cap at 100 items.
PAGE_SIZE = 100


@dataclasses.dataclass
class KustomerResumeConfig:
    # Kustomer paginates via a JSON:API `links.next` URL (absolutized against
    # the org host), so the URL is all we persist.
    next_url: str


def _clean_org_name(org_name: str) -> str:
    """Accept either the bare org subdomain or a pasted full domain/URL."""
    org = org_name.strip().removeprefix("https://").removeprefix("http://")
    org = org.split(".")[0].split("/")[0]
    if not re.fullmatch(r"[a-zA-Z0-9-]+", org):
        raise ValueError(f"Invalid Kustomer organization name: {org_name}")
    return org


def _base_url(org_name: str) -> str:
    return f"https://{_clean_org_name(org_name)}.api.kustomerapp.com"


def _ensure_same_origin(url: str, base_url: str) -> str:
    """Reject pagination/resume URLs that leave the org host.

    `links.next` is server-controlled and `urljoin` follows absolute URLs
    verbatim, so a tampered response could otherwise point our authenticated
    request (which carries the API key in its Bearer header) at an external host
    and leak the key. Compare the full origin (scheme + netloc), not a prefix, so
    look-alike hosts like `org.api.kustomerapp.com.evil.com` are rejected too."""
    parsed, base = urlparse(url), urlparse(base_url)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"Kustomer URL {url!r} does not stay on the expected host {base_url!r}")
    return url


class KustomerLinksNextPaginator(BaseNextUrlPaginator):
    """Follows Kustomer's JSON:API `links.next` cursor.

    The next link is typically a relative path; absolutize it against the org
    host and pin it to that origin so a tampered/absolute off-host link can't
    redirect our authenticated request and leak the Bearer key. An empty page
    stops pagination even when a `links.next` is present (parity with the
    hand-rolled loop, which broke on the first empty page)."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base_url = base_url

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # Stop on an empty page even if a next link is present.
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}
        next_link = (body.get("links") or {}).get("next") if isinstance(body, dict) else None

        if not next_link:
            self._has_next_page = False
            return

        # Absolutize against the org host and pin to that origin so an absolute
        # off-host URL can't leak the API key. Save state AFTER yielding (the
        # framework calls resume_hook post-yield) so a crash re-yields the last
        # page rather than skipping it (merge dedupes on primary key).
        self._next_url = _ensure_same_origin(urljoin(self._base_url, next_link), self._base_url)
        self._has_next_page = True

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            # Re-validate the persisted URL so a tampered Redis state can't
            # redirect our authenticated request off-host.
            self._next_url = _ensure_same_origin(next_url, self._base_url)
            self._has_next_page = True


def kustomer_source(
    org_name: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KustomerResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KUSTOMER_ENDPOINTS[endpoint]
    base_url = _base_url(org_name)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": KustomerLinksNextPaginator(base_url),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page[size]": PAGE_SIZE},
                    # JSON:API rows live under `data`. A missing key is a legit
                    # zero-row page (the hand-rolled loop used `.get("data", [])`),
                    # so this is NOT required — it stops rather than failing loud.
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(KustomerResumeConfig(next_url=str(state["next_url"])))

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
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(org_name: str, api_key: str) -> bool:
    """Confirm the API key and org are valid with a cheap one-customer probe.

    Role-scoped keys may lack individual read grants (403); only 401 means the
    key itself is bad. A malformed org or an unreachable API (no status) is also
    treated as invalid."""
    try:
        base_url = _base_url(org_name)
    except ValueError:
        return False

    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url}/v1/customers?{urlencode({'page[size]': 1})}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return status is not None and status != 401
