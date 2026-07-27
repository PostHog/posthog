import re
import base64
import dataclasses
from typing import Any, Optional

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
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import CONFLUENCE_ENDPOINTS

# Confluence Cloud sites always live under <subdomain>.atlassian.net. Building
# the host ourselves from a validated subdomain (rather than accepting an
# arbitrary host) keeps the API token from being sent anywhere off-Atlassian.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")


@dataclasses.dataclass
class ConfluenceResumeConfig:
    next_url: str


def _site_origin(subdomain: str) -> str:
    return f"https://{subdomain}.atlassian.net"


def _base_url(subdomain: str) -> str:
    return f"{_site_origin(subdomain)}/wiki/api/v2"


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(subdomain) and _SUBDOMAIN_RE.match(subdomain) is not None


def _get_headers(email: str, api_token: str) -> dict[str, str]:
    token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


class ConfluenceLinkPaginator(JSONResponsePaginator):
    """Confluence v2 returns the next page as a site-relative path in ``_links.next``
    (e.g. ``/wiki/api/v2/pages?cursor=...``); resolve it against the site origin so the
    client requests an absolute URL. Absence of the key signals the last page."""

    def __init__(self, site_origin: str) -> None:
        super().__init__(next_url_path="_links.next")
        self._site_origin = site_origin

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url and not self._next_url.startswith(("http://", "https://")):
            self._next_url = f"{self._site_origin}{self._next_url}"


def confluence_source(
    subdomain: str,
    email: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ConfluenceResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CONFLUENCE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            # Auth (HTTP Basic) is supplied via the framework auth config so the token is
            # redacted from logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": email, "password": api_token},
            "paginator": ConfluenceLinkPaginator(_site_origin(subdomain)),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.limit},
                    # v2 list endpoints wrap rows in `results`; a missing key means an empty page.
                    "data_selector": "results",
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the page we just emitted (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(ConfluenceResumeConfig(next_url=state["next_url"]))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(
    subdomain: str, email: str, api_token: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the Confluence API to confirm the credentials are genuine.

    A 403 at source-create (``schema_name is None``) is accepted: the token may
    be valid but lack access to the probed resource. Once a specific schema is
    being validated we surface the 403.
    """
    if not is_valid_subdomain(subdomain):
        return (
            False,
            "Invalid Confluence subdomain. Use just the site name, e.g. 'your-domain' for your-domain.atlassian.net.",
        )

    url = f"{_base_url(subdomain)}{CONFLUENCE_ENDPOINTS['spaces'].path}?limit=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(email, api_token),
    )

    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Confluence credentials. Check your email and API token."
    if status == 403:
        if schema_name is None:
            return True, None
        return False, "Your Confluence account does not have permission to access this resource."
    if status is None:
        return False, None

    return False, f"Confluence API returned status {status}."
