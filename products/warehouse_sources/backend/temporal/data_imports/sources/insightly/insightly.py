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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import INSIGHTLY_ENDPOINTS

API_VERSION = "v3.1"
# Insightly caps list pages at 500 items (default is 100).
PAGE_SIZE = 500
# Insightly exposes this server-side filter on incremental endpoints; the last synced cursor is
# injected here so an incremental sync never walks unbounded history.
UPDATED_AFTER_PARAM = "updated_after_utc"

# A pod/instance is a short region token such as `na1`, `eu1`, `aps1`.
_POD_RE = re.compile(r"^[a-z0-9]+$")
_POD_FROM_URL_RE = re.compile(r"api\.([a-z0-9]+)\.insightly\.com")


@dataclasses.dataclass
class InsightlyResumeConfig:
    # Offset (`skip`) of the next page to fetch. The `updated_after_utc` filter is rebuilt from the
    # job's incremental value at resume time, so it never needs to be persisted here.
    skip: int


def normalize_pod(raw: str) -> str:
    """Reduce whatever the user pasted to the bare Insightly pod token.

    Accepts ``na1`` or a full API URL (``https://api.na1.insightly.com/v3.1``). Raising on anything
    that isn't a plain pod token also pins outbound traffic to ``api.<pod>.insightly.com`` (no SSRF
    to arbitrary hosts).
    """
    pod = raw.strip().lower()
    match = _POD_FROM_URL_RE.search(pod)
    if match:
        pod = match.group(1)
    if not _POD_RE.match(pod):
        raise ValueError(f"Invalid Insightly pod/instance: {raw!r}")
    return pod


def base_url(pod: str) -> str:
    return f"https://api.{normalize_pod(pod)}.insightly.com/{API_VERSION}"


def _format_updated_after(value: Any) -> str:
    """Format the incremental cursor as ISO 8601 with a trailing Z, which `updated_after_utc` expects
    (e.g. ``2018-04-09T16:58:14Z``)."""
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        # Already a string cursor (e.g. the raw DATE_UPDATED_UTC value round-tripped from the DB).
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def insightly_source(
    pod: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[InsightlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INSIGHTLY_ENDPOINTS[endpoint]

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        # Offset pagination with Insightly's `top`/`skip`; a short (< top) page is the last one.
        "paginator": OffsetPaginator(
            limit=PAGE_SIZE,
            offset_param="skip",
            limit_param="top",
            total_path=None,
        ),
        # Insightly list endpoints return a bare JSON array. A non-list 200 body (a 2xx error
        # envelope, an HTML gateway page) must fail loud instead of silently syncing 0 rows.
        "data_selector_required": True,
    }

    # Only incremental endpoints expose `updated_after_utc`, and only when the job supplies a cursor.
    use_incremental = bool(
        config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value
    )
    if use_incremental:
        endpoint_config["incremental"] = {
            "start_param": UPDATED_AFTER_PARAM,
            "convert": _format_updated_after,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(pod),
            "headers": {"Accept": "application/json"},
            # HTTP Basic auth with the API key as the username and a blank password. Using the
            # framework auth keeps the key out of raised error messages / logged URLs.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            # Pin every request (including resume URLs) to api.<pod>.insightly.com — reinforces the
            # pod normalization guard so credentials can never be sent off-host.
            "allowed_hosts": [],
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
        if resume is not None:
            initial_paginator_state = {"offset": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(InsightlyResumeConfig(skip=int(state["offset"])))

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
        primary_keys=[config.primary_key],
        # Insightly paginates in record-id (creation) order, so rows for a given sync arrive roughly
        # oldest-first; DATE_UPDATED_UTC is not strictly monotonic across pages. We keep the same
        # `updated_after_utc` filter on every page (offset pagination reuses the query), so an
        # incremental sync never walks unbounded history — and if Insightly ever ignored the filter,
        # the sync degrades to full-refresh cost, never incorrect data (merge dedupes on the id).
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(pod: str, api_key: str, path: str = "/Contacts") -> Optional[int]:
    """Return the status code of a cheap authenticated probe, or ``None`` on transport error.

    Requests a single row from ``path`` so a genuine key returns 200, a bad key 401, and a key
    without scope for that resource 403. The URL is built outside the probe so an invalid-pod
    ``ValueError`` propagates rather than being flattened to ``None`` by the transport-error handler.
    """
    url = f"{base_url(pod)}{path}?{urlencode({'top': 1})}"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        auth=HttpBasicAuth(username=api_key, password=""),
    )
    return status
