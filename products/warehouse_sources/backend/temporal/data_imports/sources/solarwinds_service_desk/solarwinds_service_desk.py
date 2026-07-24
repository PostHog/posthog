import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from dateutil import parser as dateutil_parser
from requests import Response

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
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    PER_PAGE,
    SOLARWINDS_SERVICE_DESK_ENDPOINTS,
)

# SolarWinds Service Desk runs independent regional stacks that do not share data.
SOLARWINDS_SERVICE_DESK_HOSTS: dict[str, str] = {
    "us": "https://api.samanage.com",
    "eu": "https://apieu.samanage.com",
    "au": "https://apiau.samanage.com",
}
DEFAULT_REGION = "us"
# The versioned Accept header pins the payload format — without it the API may serve legacy shapes.
ACCEPT_HEADER = "application/vnd.samanage.v2.1+json"
# Cheap list probe used to confirm a token is genuine. The token inherits its creator's role, so a
# 403 here can still mean a valid token — the caller decides how to treat it.
DEFAULT_PROBE_PATH = "/users.json"
# SolarWinds reports the page count in this response header, not the body.
TOTAL_PAGES_HEADER = "X-Total-Pages"


@dataclasses.dataclass
class SolarwindsServiceDeskResumeConfig:
    # Next 1-indexed page to fetch. None means start from page 1.
    next_page: int | None = None
    # `updated_from` filter computed when the run started. Persisted so a resumed run issues the
    # exact same query instead of recomputing a window whose page boundaries would shift mid-crawl.
    updated_from: str | None = None


def base_url(region: Optional[str]) -> str:
    resolved = (region or DEFAULT_REGION).lower()
    return SOLARWINDS_SERVICE_DESK_HOSTS.get(resolved, SOLARWINDS_SERVICE_DESK_HOSTS[DEFAULT_REGION])


def _headers(api_token: str) -> dict[str, str]:
    # Auth rides a vendor-specific header, and the versioned Accept header pins the payload format.
    return {
        "X-Samanage-Authorization": f"Bearer {api_token}",
        "Accept": ACCEPT_HEADER,
    }


def _format_updated_from(value: Any) -> Optional[str]:
    """Format an incremental cursor as the ISO 8601 UTC value the `updated_from` filter expects.

    Returns None when the watermark can't be interpreted, which safely degrades that run to a full
    crawl rather than guessing at a window.
    """
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, OverflowError):
            return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        aware = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return None
    # The documented examples use minute precision ('2023-11-29T08:00'); truncating rounds the
    # window start down, so boundary rows are re-fetched and merge dedupes them on `id`.
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def _unwrap_row(item: dict[str, Any], wrapper_key: str) -> dict[str, Any]:
    """Normalize a list item to a bare record dict.

    The official response samples are inconsistent: some list endpoints show bare records while
    others wrap each row under its singular resource name (e.g. ``{"problem": {...}}``). A real
    record is never a single-key dict of its own singular name, so unwrapping is unambiguous.
    """
    if set(item.keys()) == {wrapper_key} and isinstance(item[wrapper_key], dict):
        return item[wrapper_key]
    return item


class SolarwindsPageNumberPaginator(PageNumberPaginator):
    """Page-number pagination that stops on the documented ``X-Total-Pages`` header.

    SolarWinds reports the page count in a response header rather than the body, and may clamp
    ``per_page`` below the requested size — so a short page must never end the crawl; only an empty
    page or reaching the header's last page terminates it. Resume is inherited from
    ``PageNumberPaginator`` (page number in/out).
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        raw_total = response.headers.get(TOTAL_PAGES_HEADER)
        if raw_total is not None and raw_total.isdigit():
            # ``self.page`` now points at the NEXT page (super incremented it); base_page is 1, so
            # the last valid page equals the header's total.
            if self.page > int(raw_total):
                self._has_next_page = False


def solarwinds_service_desk_source(
    region: Optional[str],
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SolarwindsServiceDeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_page:
        initial_paginator_state = {"page": resume.next_page}
        # A resumed run reuses the persisted window instead of recomputing one from a watermark
        # that may have moved on.
        updated_from = resume.updated_from
    else:
        updated_from = None
        if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
            updated_from = _format_updated_from(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(region),
            # Only the non-secret Accept header goes here; auth rides the framework auth config so
            # its value is redacted from logs and raised error messages.
            "headers": {"Accept": ACCEPT_HEADER},
            "auth": {
                "type": "api_key",
                "api_key": f"Bearer {api_token}",
                "name": "X-Samanage-Authorization",
                "location": "header",
            },
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PER_PAGE, "updated_from": updated_from},
                    # A 200 body that isn't a list means the response shape changed — retry rather
                    # than silently ingesting a stray object as a single row.
                    "data_selector_malformed_retryable": True,
                    "paginator": SolarwindsPageNumberPaginator(base_page=1),
                },
                # Some list endpoints wrap each row under its singular resource name — unwrap to
                # the bare record before it's written.
                "data_map": lambda item, _key=config.wrapper_key: _unwrap_row(item, _key),
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(
                SolarwindsServiceDeskResumeConfig(next_page=int(state["page"]), updated_from=updated_from)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental is injected as the static `updated_from` param above, so the framework's
        # cursor machinery is unused.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # List ordering is undocumented (no sort params, likely newest-first): "desc" makes the
        # pipeline commit the incremental watermark only after a completed sync instead of
        # checkpointing a possibly-too-high value per batch.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(region: Optional[str], api_token: str, path: str | None = None) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the API token.

    At source-create (``path`` is None) a 403 is a genuine token whose owner's role can't read the
    probe resource — that must not block connecting the source; a schema-scoped probe fails a 403 so
    the user sees which table their role can't read.
    """
    probe_path = path or DEFAULT_PROBE_PATH
    url = f"{base_url(region)}{probe_path}?{urlencode({'per_page': 1, 'page': 1})}"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_headers(api_token),
        timeout=15,
    )
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid SolarWinds Service Desk API token"
    if status == 403:
        if path is None:
            return True, None
        return False, "Your SolarWinds Service Desk token does not have permission to read this resource"
    if status is None:
        return False, "Could not connect to SolarWinds Service Desk"
    return False, f"SolarWinds Service Desk returned HTTP {status}"
