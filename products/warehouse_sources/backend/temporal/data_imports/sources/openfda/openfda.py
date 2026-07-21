"""openFDA (U.S. Food and Drug Administration) REST API transport.

openFDA (https://api.fda.gov) is the FDA's free public API over drug, device, and food regulatory
datasets (adverse events, recalls/enforcement reports, drug labeling, 510(k) clearances, the NDC
directory). Every dataset is its own endpoint with its own schema and date field; responses wrap the
records in `{"meta": ..., "results": [...]}`.

Pagination is a `search_after` cursor exposed via the HTTP `Link: rel="next"` header (the `skip`
offset param is capped at 25,000, so the cursor is the only way to walk a large dataset). Each next
URL is absolute and pre-encoded, so we follow it verbatim and it preserves the original `search`
(date filter) and `sort` params — which lets an incremental sync stay server-side-bounded on every
page. A single page has no next link once the results are exhausted, which is the loop terminator.

Incremental sync uses the endpoint's date field: `search=<field>:[<watermark> TO 99991231]` with
`sort=<field>:asc`. openFDA date fields are `YYYYMMDD` (a few, like `decision_date`, arrive dashed,
but the API accepts `YYYYMMDD` in the search filter uniformly), and the range is inclusive on both
ends, so we re-request the watermark day each run and let the delta merge dedupe on the primary key.

Auth is an optional free API key. Without one, openFDA throttles to 240 req/min and 1,000 req/day
per IP; with one, 240 req/min and 120,000 req/day per key. The key is sent as the HTTP Basic auth
username (openFDA's documented header method) so it never lands in a logged URL or in the saved
cursor state.

An empty result set surfaces as HTTP 404 with `{"error": {"code": "NOT_FOUND"}}`, not an empty
`results` array — so a 404 is treated as "no matching records" and ends the sync cleanly (common on
an up-to-date incremental run whose watermark is already at the latest record).
"""

import dataclasses
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Response
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    HttpBasicAuthConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.settings import (
    OPENFDA_ENDPOINTS,
    OpenFDAEndpointConfig,
)

OPENFDA_BASE_URL = "https://api.fda.gov"
_OPENFDA_HOST = "api.fda.gov"

# openFDA caps a single search request at 1,000 results; larger values 400.
PAGE_SIZE = 1000

# Inclusive upper bound for the incremental date-range filter — effectively "no ceiling".
_MAX_DATE = "99991231"


@dataclasses.dataclass
class OpenFDAResumeConfig:
    # Absolute, pre-encoded `Link: rel="next"` URL to fetch next. None means "start from the first
    # page" (the initial URL is rebuilt from the endpoint config + watermark).
    next_url: str | None = None


def _is_valid_openfda_url(url: str) -> bool:
    """Only absolute `https://api.fda.gov/...` URLs may be followed. A pagination cursor comes from a
    `Link` header or from resumed state — both are attacker-influenceable, and following one off-host
    would leak the API key (sent as Basic auth) or hit an internal address."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == _OPENFDA_HOST


class OpenFDALinkPaginator(HeaderLinkPaginator):
    """`HeaderLinkPaginator` that refuses to follow an off-host or non-HTTPS `next` link.

    A pagination cursor comes from a `Link` header (this page's response) or from resumed state
    (`set_resume_state`) — both are attacker-influenceable. Following one off `api.fda.gov`, or over
    plain HTTP, would leak the API key (sent as Basic auth) to another origin or hit an internal
    address, so a poisoned cursor fails loud (non-retryable `ValueError`) instead of being requested.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None and not _is_valid_openfda_url(self._next_url):
            raise ValueError(f"openFDA returned an off-host pagination URL, refusing to follow: {self._next_url}")

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None and not _is_valid_openfda_url(next_url):
            raise ValueError(f"openFDA resume cursor is not a valid api.fda.gov URL: {next_url}")
        super().set_resume_state(state)


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": "PostHog-DataWarehouse"}


def _format_date_value(value: Any) -> str:
    """Format an incremental watermark as the `YYYYMMDD` openFDA expects in a search date range."""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    # A raw string watermark (e.g. "20200101" or "2020-01-01"): strip separators to YYYYMMDD.
    return str(value).replace("-", "")[:8]


def _build_params(
    config: OpenFDAEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    field = incremental_field or config.incremental_field
    if field is not None:
        # Sort ascending on the date field so the pipeline's watermark advances monotonically as we
        # page (sort_mode="asc"). Full-refresh endpoints have no date field and page on the cursor's
        # internal ordering without a sort.
        params["sort"] = f"{field}:asc"

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            low = _format_date_value(db_incremental_field_last_value)
            params["search"] = f"{field}:[{low} TO {_MAX_DATE}]"

    return params


def _make_basic_auth(api_key: str | None) -> HTTPBasicAuth | None:
    # openFDA accepts the API key as the HTTP Basic auth username (empty password). Sending it in the
    # header keeps it out of logged URLs and out of the saved cursor state.
    return HTTPBasicAuth(api_key, "") if api_key else None


def _auth_config(api_key: str | None) -> Optional[HttpBasicAuthConfig]:
    # Framework http_basic auth (key as username, empty password) so the credential is injected as an
    # Authorization header rather than a hand-built one. openFDA allows the unauthenticated tier, so a
    # blank key sends no auth at all.
    return {"type": "http_basic", "username": api_key, "password": ""} if api_key else None


def openfda_source(
    api_key: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpenFDAResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = OPENFDA_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": OPENFDA_BASE_URL,
            "headers": _get_headers(),
            "auth": _auth_config(api_key),
            # openFDA paginates via the `Link: rel="next"` header; the custom paginator rejects a
            # poisoned off-host/non-HTTPS cursor before it is requested.
            "paginator": OpenFDALinkPaginator(),
            # Disallow following any redirect — a 3xx could smuggle the request (and the API key sent
            # as Basic auth) to another origin.
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                    # openFDA guarantees `results` on every 200 (empty sets come back as a 404,
                    # handled below); a missing key is an unexpected shape we surface rather than
                    # silently syncing 0 rows.
                    "data_selector_required": True,
                    # openFDA returns 404 (not an empty results array) when nothing matches — expected
                    # at the tail of an incremental run. Treat it as a clean terminal page, not an
                    # error, so a caught-up sync ends instead of failing.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
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
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the just-yielded page (merge dedupes) rather than skipping it. The final page saves nothing.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(OpenFDAResumeConfig(next_url=state["next_url"]))

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
        # Incremental endpoints request sort=<field>:asc so rows arrive oldest-first and the watermark
        # advances safely after each batch. Full-refresh endpoints add no sort (they page on the bare
        # cursor), so their arrival order is undefined — don't claim "asc" for them.
        sort_mode="asc" if config.incremental_field else None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str | None) -> bool:
    # A single cheap probe of the drug enforcement endpoint confirms reachability and (if provided)
    # that the key is accepted. openFDA allows unauthenticated access, so a blank key is still valid —
    # it just gets the lower rate-limit tier.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(
            redact_values=(api_key,) if api_key else (),
            allow_redirects=False,
            # Disable urllib3 adapter retries — a slow/unreachable endpoint shouldn't hang the
            # connect-time UI probe for minutes.
            retry=Retry(total=0),
        ),
        f"{OPENFDA_BASE_URL}/drug/enforcement.json?limit=1",
        headers=_get_headers(),
        auth=_make_basic_auth(api_key),
        timeout=30,
    )
    return ok
