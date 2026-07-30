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
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.settings import VANTAGE_ENDPOINTS

VANTAGE_HOST = "api.vantage.sh"
VANTAGE_BASE_URL = f"https://{VANTAGE_HOST}/v2"

# The Vantage API caps `limit` at 1000; use the max to minimise the number of paginated requests
# (and thus stay well under the ~1,000 requests/hour and ~20 requests/minute per-key rate limits).
PAGE_SIZE = 1000


class VantageUntrustedURLError(Exception):
    pass


def _is_trusted_vantage_url(url: str) -> bool:
    # `links.next` (and any resumed cursor derived from it) is server-controlled data. Before we
    # attach the bearer token and fetch it, pin the URL to Vantage's own HTTPS host and `/v2/` API
    # path so a spoofed or compromised response can't redirect the credential to an
    # attacker-controlled origin.
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname == VANTAGE_HOST and parsed.path.startswith("/v2/")


class VantageTrustedJSONPaginator(JSONResponsePaginator):
    """Follows `links.next` in the response body, but refuses any next/resume URL that isn't on
    Vantage's own HTTPS host under the `/v2/` API path — the URL is server-controlled and must never
    be able to carry the bearer token off-origin. Rejection happens before the request is issued."""

    def __init__(self) -> None:
        super().__init__(next_url_path="links.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page:
            self._reject_if_untrusted(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._reject_if_untrusted(state.get("next_url"))
        super().set_resume_state(state)

    @staticmethod
    def _reject_if_untrusted(url: Optional[str]) -> None:
        if url is not None and not _is_trusted_vantage_url(url):
            raise VantageUntrustedURLError(
                f"Refusing to fetch untrusted Vantage URL: host must be {VANTAGE_HOST} over HTTPS"
            )


@dataclasses.dataclass
class VantageResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the response `links.next`. Vantage
    # encodes `page`/`limit` into it, so following it is enough to resume where we left off.
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # `/ping` is the cheapest authenticated endpoint - it requires a valid read token and returns
    # 401 for a bad/expired one, without touching any cost data (so it can't trip the stricter
    # Cost Report rate limits).
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{VANTAGE_BASE_URL}/ping",
        headers=_get_headers(api_key),
    )
    return ok


def vantage_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
) -> SourceResponse:
    config = VANTAGE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": VANTAGE_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so the token is redacted from
            # logs and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": VantageTrustedJSONPaginator(),
            # `links.next` is server-controlled: pin every request to Vantage's own host and never
            # follow a redirect that could forward the bearer token off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Cap page size on the first request; `links.next` carries limit/page thereafter.
                    "params": {"limit": PAGE_SIZE},
                    # Rows nest under the endpoint's own key (e.g. "cost_reports"). A missing key on a
                    # 200 yields zero rows (matching the prior `data.get(key, [])`), not a hard error.
                    "data_selector": config.data_key,
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(VantageResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
