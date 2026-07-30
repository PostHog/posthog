import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import (
    TEAMWORK_ENDPOINTS,
    TeamworkEndpointConfig,
)

# Max page size accepted by the majority of V3 endpoints.
PAGE_SIZE = 500
# A single V3 request is hard-capped at 50,000 records (= 100 pages of 500). We stop one run at that
# boundary rather than letting the API error out. Incremental endpoints resume past it on the next
# scheduled run (the cursor watermark has advanced); full-refresh endpoints can't.
MAX_PAGES = 100


@dataclasses.dataclass
class TeamworkResumeConfig:
    # Next 1-based page number to fetch within the current sync window.
    page: int = 1
    # The `updatedAfter` cursor used for this sync's window, so a resumed run rebuilds the same query.
    updated_after: str | None = None


def normalize_host(site: str) -> str:
    """Turn a user-entered Teamwork site into a bare hostname.

    Accepts a subdomain (``mycompany``), a full host (``mycompany.teamwork.com``), or a pasted URL
    (``https://mycompany.teamwork.com/``). A value with no dot is treated as a subdomain of
    ``teamwork.com``. Region/custom hosts (``mycompany.eu.teamwork.com``) are preserved as-is.
    """
    host = site.strip()
    host = host.removeprefix("https://").removeprefix("http://")
    host = host.split("/", 1)[0].strip().rstrip(".").lower()
    if "." not in host:
        host = f"{host}.teamwork.com"
    return host


def base_url(host: str) -> str:
    return f"https://{host}/projects/api/v3"


def _format_updated_after(value: Any) -> str:
    """Format a cursor value as the ``yyyy-mm-ddThh:mm:ssZ`` string the V3 ``updatedAfter`` param wants."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class TeamworkPaginator(PageNumberPaginator):
    """Page-number paginator that also honors Teamwork's ``meta.page.hasMore`` stop signal.

    The built-in ``PageNumberPaginator`` stops only on an empty page or ``maximum_page``, but Teamwork
    signals the last page via ``meta.page.hasMore=false`` on a page that still carries rows — so we
    stop there rather than paying one extra empty-page request. A single V3 request window is also
    hard-capped at ``MAX_PAGES`` pages, enforced here via ``maximum_page``. Resume (``page``) is
    inherited from the base paginator.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page", maximum_page=MAX_PAGES)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        try:
            has_more = bool(response.json().get("meta", {}).get("page", {}).get("hasMore", False))
        except Exception:
            has_more = False

        self.page += 1

        if not has_more or (self.maximum_page is not None and self.page > self.maximum_page):
            self._has_next_page = False
            return

        self._has_next_page = True


def _build_params(config: TeamworkEndpointConfig, updated_after: str | None) -> dict[str, Any]:
    # `page` is injected by the paginator; the rest are static for the whole sync window.
    params: dict[str, Any] = {"pageSize": PAGE_SIZE}
    if config.order_by:
        params["orderBy"] = config.order_by
        params["orderMode"] = "asc"
    if updated_after:
        params["updatedAfter"] = updated_after
    return params


def teamwork_source(
    host: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TeamworkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TEAMWORK_ENDPOINTS[endpoint]

    is_incremental = should_use_incremental_field and config.incremental_field is not None
    updated_after = (
        _format_updated_after(db_incremental_field_last_value)
        if is_incremental and db_incremental_field_last_value
        else None
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}
            # A resumed run rebuilds the SAME query window it started with, not a freshly recomputed one.
            updated_after = resume.updated_after

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(host),
            # Only non-secret headers here; the API key travels via framework http_basic auth
            # (redacted from logs) using the key as username and any value as password.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": api_key, "password": "x"},
            "paginator": TeamworkPaginator(),
            # Pin every request to the validated host and reject any redirect: the Basic auth
            # header must never be forwarded off the host boundary (SSRF / credential leak).
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, updated_after),
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash resumes at
        # the next page (any re-fetch is deduped on the primary key by the merge).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(
                TeamworkResumeConfig(page=int(state["page"]), updated_after=updated_after)
            )

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
        # Rows are requested ascending (orderMode=asc), so the pipeline can checkpoint the watermark
        # after every batch and resume safely mid-sync.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(host: str, api_key: str) -> bool:
    # /me.json is the cheapest authenticated probe — it only needs a valid key, no extra scopes.
    # allow_redirects=False: a redirect would forward the Basic auth header off the validated host.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(allow_redirects=False),
        f"{base_url(host)}/me.json",
        headers={"Accept": "application/json"},
        auth=HttpBasicAuth(username=api_key, password="x"),
    )
    return ok
