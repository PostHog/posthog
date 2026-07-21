import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import HETZNER_ENDPOINTS

# Single global base URL — Hetzner Cloud has no regional hosts.
HETZNER_BASE_URL = "https://api.hetzner.cloud/v1"

# Max page size the API accepts; anything larger is clamped by the server. Bigger pages mean fewer
# round trips against the 3600 req/hour budget.
PAGE_SIZE = 50

# Hetzner list endpoints are 1-indexed.
FIRST_PAGE = 1


@dataclasses.dataclass
class HetznerResumeConfig:
    # Page number to fetch first on resume. The framework checkpoints the NEXT page after a page has
    # been yielded, so a crash mid-page resumes onto that in-flight page and re-reads it rather than
    # skipping its un-yielded tail (dropping rows is worse than re-reading a page). These tables are
    # full refresh with an `id` primary key, so any rows a re-fetched page duplicates are wiped by the
    # next non-resumed run (which overwrites the table from scratch) or deduped on merge.
    page: int = FIRST_PAGE


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def hetzner_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HETZNER_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    if config.sort is not None:
        params["sort"] = config.sort

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HETZNER_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
            # Page-number pagination; `meta.pagination.last_page` is the TOTAL number of pages, so the
            # paginator stops after the last page instead of paying one extra empty-page request.
            # stop_after_empty_page (default) is the fallback when a response omits the total.
            "paginator": PageNumberPaginator(
                base_page=FIRST_PAGE,
                page_param="page",
                total_path="meta.pagination.last_page",
            ),
            # Disable redirect following so a 3xx can never replay the Authorization header to another
            # host — the SSRF guard the hand-rolled transport used.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # The list lives under the endpoint's envelope key, e.g. {"servers": [...]}. A
                    # missing key means an empty page (Hetzner never returns 200 without it), so a
                    # non-required selector lets the paginator stop rather than failing loud.
                    "data_selector": config.response_key,
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
        # Persist only when a next page remains; the framework calls this AFTER a page is yielded with
        # the NEXT page to fetch, so a crash re-reads the in-flight page (bounded, deduped) rather than
        # skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(HetznerResumeConfig(page=int(state["page"])))

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
        # id:asc (or default order for the catalog endpoints) — rows arrive oldest-id first.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """One cheap authenticated probe to confirm the token is genuine. Hetzner project tokens grant
    read access to every resource in the project (a read-only token still reads all of them), so
    there is no per-endpoint scope to check — a valid token can sync any table."""
    # redact_values masks the token in logged URLs / captured samples; allow_redirects=False keeps a
    # redirect from ever replaying the Authorization header to another host.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        f"{HETZNER_BASE_URL}/ssh_keys?per_page=1",
        headers={"Authorization": f"Bearer {api_token}", **_non_secret_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Hetzner Cloud API token"
    if status is None:
        return False, "Could not reach the Hetzner Cloud API"
    return False, f"Hetzner Cloud API returned HTTP {status}"
