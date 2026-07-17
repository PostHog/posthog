import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.settings import INVOICED_ENDPOINTS

INVOICED_BASE_URL = "https://api.invoiced.com"
INVOICED_HOST = "api.invoiced.com"
# List endpoints paginate GitHub-style (page/per_page + Link header) in pages of up to 100.
PAGE_SIZE = 100
# Cheap list endpoint used to confirm an API key is genuine. Invoiced API keys are
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/customers"


class InvoicedUntrustedURLError(Exception):
    """A pagination URL (resumed or upstream) pointed somewhere other than the Invoiced API."""


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Invoiced API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `Link` header URLs are followed
    verbatim with the customer's API key installed as HTTP Basic auth. Validating the scheme and host
    keeps a poisoned resume state or a hostile upstream response from retargeting the request at
    another host and leaking the key (SSRF). Returns the URL unchanged when it is trusted.
    """
    parts = urlsplit(url)
    if not (parts.scheme == "https" and parts.netloc == INVOICED_HOST):
        raise InvoicedUntrustedURLError(f"Refusing to follow pagination URL outside {INVOICED_BASE_URL}")
    return url


@dataclasses.dataclass
class InvoicedResumeConfig:
    # Full URL of the next page, taken verbatim from the Link header's rel="next". It carries
    # the original request's per_page/sort/updated_after params, so a crashed sync resumes from
    # the page after the last one yielded; merge dedupes the re-pulled page on `id`.
    next_url: str | None = None


def _to_unix_timestamp(value: Any) -> int:
    """Convert an incremental cursor to the UNIX epoch integer `updated_after` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    return int(value)


def invoiced_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[InvoicedResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INVOICED_ENDPOINTS[endpoint]

    # An explicit ascending updated_at sort keeps page traversal deterministic and lets the
    # pipeline checkpoint the incremental watermark per batch (sort_mode="asc"). `sort` is
    # documented on every list endpoint we sync ("Column to sort by, i.e. name asc").
    params: dict[str, Any] = {"per_page": PAGE_SIZE, "sort": "updated_at asc"}

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        # List endpoints return a top-level JSON array; a non-list body means the response shape
        # changed — fail loud rather than wrapping a stray object as a single row.
        "data_selector_required": True,
        # GitHub-style pagination: the next page lives in the Link header's rel="next".
        "paginator": HeaderLinkPaginator(),
    }

    use_incremental = should_use_incremental_field and db_incremental_field_last_value is not None
    if use_incremental:
        # Every list endpoint documents a server-side `updated_after` UNIX-timestamp filter; inject
        # the last synced value as that filter so the sync only pulls rows touched since.
        endpoint_config["incremental"] = {
            "start_param": "updated_after",
            "cursor_path": "updated_at",
            "convert": _to_unix_timestamp,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": INVOICED_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Invoiced authenticates via HTTP Basic with the API key as the username and a blank
            # password. The framework applies (and redacts) it, so no hand-built Authorization header.
            "auth": HttpBasicAuth(username=api_key, password=""),
            # Pin every request — including paginator next-page links and seeded resume URLs — to the
            # Invoiced API host, and reject any 3xx, so a spoofed link or redirect can't retarget the
            # authenticated request at another origin (SSRF). The scheme/host guard in the resume hook
            # below adds the https-downgrade rejection host-pinning alone would miss.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            # Resume state comes from Redis — validate before sending the API key to it.
            initial_paginator_state = {"next_url": _validate_pagination_url(resume.next_url)}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) and merge dedupes the re-pulled
        # page on the primary key. The upstream-supplied next URL is validated before it's stored so
        # a hostile Link header aborts the sync instead of poisoning the saved resume state.
        next_url = state.get("next_url") if state else None
        if next_url:
            resumable_source_manager.save_state(InvoicedResumeConfig(next_url=_validate_pagination_url(next_url)))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        # Rows are requested with an explicit `sort=updated_at asc`.
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API key.

    Invoiced API keys are account-wide, so one probe validates access to every list endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{INVOICED_BASE_URL}{DEFAULT_PROBE_PATH}?per_page=1",
        auth=HttpBasicAuth(username=api_key, password=""),
        timeout=15,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Invoiced API key"
    if status is None:
        return False, "Could not connect to Invoiced"
    return False, f"Invoiced returned HTTP {status}"
