import re
import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.settings import (
    THINKIFIC_COURSES_ENDPOINTS,
    ThinkificCoursesEndpointConfig,
)

THINKIFIC_BASE_URL = "https://api.thinkific.com/api/public/v1"

# Thinkific subdomains are the `<subdomain>.thinkific.com` slug, sent as the X-Auth-Subdomain header.
_SUBDOMAIN_RE = re.compile(r"^[a-zA-Z0-9-]+$")


@dataclasses.dataclass
class ThinkificCoursesResumeConfig:
    # Top-level endpoints resume by page number: Thinkific paginates by page (meta.pagination), so
    # the 1-based next page index is the only state needed.
    next_page: Optional[int] = None
    # Fan-out endpoints resume by parent: child paths already fully synced, the path in progress,
    # and that path's paginator state (see rest_source._make_paginate_dependent_resource).
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(_SUBDOMAIN_RE.match(subdomain))


def _get_headers(api_key: str, subdomain: str) -> dict[str, str]:
    return {
        "X-Auth-API-Key": api_key,
        "X-Auth-Subdomain": subdomain,
        "Accept": "application/json",
    }


def _client_config(api_key: str, subdomain: str) -> ClientConfig:
    # The API key travels via the framework `auth` config (X-Auth-API-Key) so it's redacted from logs
    # and error messages; only the non-secret subdomain routing header and Accept go on the session.
    # `capture=False`: Thinkific responses carry student names/emails and free-text review and coupon
    # notes the name-based sample scrubbers can't recognise, so keep bodies out of HTTP sample storage
    # entirely (requests are still metered and logged). `redact_values=(api_key,)` masks the key in
    # logged URLs; `allow_redirects=False` never replays the X-Auth-API-Key header to a redirect target.
    session = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)
    return {
        "base_url": THINKIFIC_BASE_URL,
        "headers": {"X-Auth-Subdomain": subdomain, "Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-Auth-API-Key", "location": "header"},
        "session": session,
        # Pin every request (and the X-Auth-API-Key header) to the Thinkific host and refuse to
        # follow a 3xx, so a server-side redirect can never forward the credential headers off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _paginator() -> PageNumberPaginator:
    # Page-number pagination; `meta.pagination.total_pages` is the total PAGE count, so the
    # paginator stops after the last page without paying an extra empty-page request. The public
    # API exposes no sort param; list endpoints return id-ascending (≈ creation order).
    return PageNumberPaginator(base_page=1, page=1, total_path="meta.pagination.total_pages")


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


def _make_source_response(
    config: ThinkificCoursesEndpointConfig, items: Any, column_hints: Optional[dict[str, Any]] = None
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Incremental enrollments sync stays correct regardless of exact ordering because the
        # day-granularity filter is inclusive and merge dedupes on the primary key.
        sort_mode="asc",
        column_hints=column_hints,
    )


def _fanout_source(
    config: ThinkificCoursesEndpointConfig,
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ThinkificCoursesResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The fan-out checkpoints after each child page and after each parent completes; saving the
        # completed-parents list means a retry skips parents already fully synced (merge dedupes any
        # re-yielded in-progress page).
        if state is not None:
            resumable_source_manager.save_state(
                ThinkificCoursesResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=THINKIFIC_COURSES_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key, subdomain),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Explicit paginator/data_selector on both levels: the child path embeds its resolve
            # placeholder in a query string, which the single-entity heuristic would otherwise
            # mistake for a fetch-one-record endpoint and stop after a single page.
            parent_endpoint_extra={"paginator": _paginator(), "data_selector": "items"},
            child_endpoint_extra={"paginator": _paginator(), "data_selector": "items"},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )
    return _make_source_response(config, lambda: dependent_resource)


def thinkific_courses_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ThinkificCoursesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = THINKIFIC_COURSES_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_key, subdomain, endpoint, team_id, job_id, resumable_source_manager)

    params: dict[str, Any] = {"limit": config.page_size}
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        # Inclusive, day-granularity server-side filter on `updated_at`: re-fetch the whole boundary
        # day so updates that landed after the watermark within the same day aren't skipped. Re-pulled
        # rows are deduped by the primary key on merge. We deliberately use `updated_on_or_after`
        # rather than the exclusive `updated_after` to avoid that same-day gap.
        params["query[updated_on_or_after]"] = _format_incremental_date(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, subdomain),
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
                    "paginator": _paginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ThinkificCoursesResumeConfig(next_page=int(state["page"])))

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

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def validate_credentials(api_key: str, subdomain: str, endpoint_path: str = "/courses") -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key + subdomain are genuine. Returns (is_valid, status_code);
    status_code is None when the request never completed."""
    url = f"{THINKIFIC_BASE_URL}{endpoint_path}?{urlencode({'page': 1, 'limit': 1})}"
    return validate_via_probe(
        # The X-Auth-API-Key header rides on the probe; pin redirects off on the session so one can't
        # replay it to a redirect target off the Thinkific host during validation. `capture=False`:
        # a successful /courses probe response can contain Thinkific customer data (student names,
        # free-text notes), so keep it out of HTTP sample storage just like the sync path's session.
        lambda: make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False),
        url,
        headers=_get_headers(api_key, subdomain),
    )
