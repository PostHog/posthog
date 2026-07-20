import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

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
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import THINKIFIC_ENDPOINTS

THINKIFIC_BASE_URL = "https://api.thinkific.com/api/public/v1"

# Thinkific subdomains are the `<subdomain>.thinkific.com` slug, sent as the X-Auth-Subdomain header.
_SUBDOMAIN_RE = re.compile(r"^[a-zA-Z0-9-]+$")


@dataclasses.dataclass
class ThinkificResumeConfig:
    # 1-based page number to fetch next. Thinkific paginates by page number (meta.pagination), so the
    # page index is the only state needed to resume an endpoint mid-sync.
    next_page: int


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(_SUBDOMAIN_RE.match(subdomain))


def _get_headers(api_key: str, subdomain: str) -> dict[str, str]:
    return {
        "X-Auth-API-Key": api_key,
        "X-Auth-Subdomain": subdomain,
        "Accept": "application/json",
    }


def _client_headers(subdomain: str) -> dict[str, str]:
    # The API key travels via the framework `auth` config (X-Auth-API-Key) so it's redacted from logs
    # and error messages; only the non-secret subdomain routing header and Accept go here.
    return {"X-Auth-Subdomain": subdomain, "Accept": "application/json"}


def _format_incremental_date(value: Any) -> str:
    """Thinkific's query[updated_*] filters take an ISO 8601 *date* (day granularity), so we reduce
    the stored cursor (a datetime watermark) to its UTC date."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Already a string cursor (e.g. an ISO timestamp) - keep the leading date portion.
    return str(value)[:10]


def thinkific_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ThinkificResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = THINKIFIC_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": config.page_size}
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        # Inclusive, day-granularity server-side filter on `updated_at`: re-fetch the whole boundary
        # day so updates that landed after the watermark within the same day aren't skipped. Re-pulled
        # rows are deduped by the primary key on merge. We deliberately use `updated_on_or_after`
        # rather than the exclusive `updated_after` to avoid that same-day gap.
        params["query[updated_on_or_after]"] = _format_incremental_date(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": THINKIFIC_BASE_URL,
            "headers": _client_headers(subdomain),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Auth-API-Key", "location": "header"},
            # Pin every request (and the X-Auth-API-Key header) to the Thinkific host and refuse to
            # follow a 3xx, so a server-side redirect can never forward the credential headers off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Thinkific wraps every list response as {"items": [...], "meta": {"pagination": {...}}};
                    # records carry their fields at the top level (no attributes envelope). A missing/empty
                    # `items` is a legit zero-row page (paginator stops), so this is not `_required`.
                    "data_selector": "items",
                    # Page-number pagination; `meta.pagination.total_pages` is the total PAGE count, so the
                    # paginator stops after the last page without paying an extra empty-page request. The
                    # public API exposes no sort param; list endpoints return id-ascending (≈ creation order).
                    "paginator": PageNumberPaginator(base_page=1, page=1, total_path="meta.pagination.total_pages"),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ThinkificResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental is expressed as a static server-side filter param above (day granularity), so the
        # framework doesn't inject its own cursor param.
        None,
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
        # Incremental enrollments sync stays correct regardless of exact ordering because the
        # day-granularity filter is inclusive and merge dedupes on the primary key.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, subdomain: str, endpoint_path: str = "/courses") -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key + subdomain are genuine. Returns (is_valid, status_code);
    status_code is None when the request never completed."""
    url = f"{THINKIFIC_BASE_URL}{endpoint_path}?{urlencode({'page': 1, 'limit': 1})}"
    return validate_via_probe(
        # The X-Auth-API-Key header rides on the probe; pin redirects off on the session so one can't
        # replay it to a redirect target off the Thinkific host during validation.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        url,
        headers=_get_headers(api_key, subdomain),
    )
