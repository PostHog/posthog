import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.settings import MAILOSAUR_ENDPOINTS

# All Mailosaur API traffic is HTTPS against the single documented host.
MAILOSAUR_BASE_URL = "https://mailosaur.com"

# Messages list pagination — itemsPerPage caps at 1000 (default 50); pull the max to minimize round-trips.
MESSAGES_PAGE_SIZE = 1000

MAILOSAUR_HEADERS = {"Accept": "application/json"}


@dataclasses.dataclass
class MailosaurResumeConfig:
    # Legacy fields from the hand-rolled fan-out: a stable server-id bookmark (not a positional
    # index) plus the next page to fetch for it. Kept (now with defaults) so state written by the
    # previous implementation still deserializes via `ResumableSourceManager._load_json`. When only
    # these are present (old saved state) the fan-out restarts from the first server — a re-fetch the
    # merge dedupes on the (server, id) primary key.
    server_id: str | None = None
    page: int = 0
    # Framework fan-out / paginator resume snapshot for the current endpoint. `None` when only the
    # legacy fields are set, and for the non-fan-out endpoints (servers, usage_transactions), which
    # are a single request with nothing to resume.
    paginator_state: dict[str, Any] | None = None


def _format_received_after(value: Any) -> str | None:
    """Format an incremental cursor value as an ISO-8601 UTC timestamp for `receivedAfter`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # The messages cursor is a DateTime field, so anything else is a bug — fail loud rather than
    # sending Mailosaur an unparseable receivedAfter it would silently ignore (a full re-fetch).
    raise TypeError(f"Unsupported receivedAfter value type: {type(value)!r}")


def _rename_server(row: dict[str, Any]) -> dict[str, Any]:
    """Message summaries omit their parent server, so the fan-out injects it via
    `include_from_parent` under the framework's `_servers_id` key. Rename it to `server` to make the
    (server, id) primary key unique table-wide, exactly as the hand-rolled source did."""
    if "_servers_id" in row:
        row["server"] = row.pop("_servers_id")
    return row


def _build_resources(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> list[EndpointResource | str]:
    config = MAILOSAUR_ENDPOINTS[endpoint]

    if not config.fan_out_over_servers:
        # Single-request endpoints (servers, usage_transactions) that return the full table at once.
        return [
            {
                "name": endpoint,
                "endpoint": {"path": config.path, "data_selector": "items"},
            }
        ]

    # Fan out message summaries over every server. `server` rides in a query param, so embed the
    # resolve placeholder in the path (the resolve mechanism only substitutes into the path). The
    # paginator then appends its own page param with `&`.
    messages_params: dict[str, Any] = {
        "server": {"type": "resolve", "resource": "servers", "field": "id"},
        "itemsPerPage": MESSAGES_PAGE_SIZE,
    }
    received_after = (
        _format_received_after(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )
    if received_after:
        # `receivedAfter` bounds the low end server-side, so incremental syncs only walk the delta.
        messages_params["receivedAfter"] = received_after

    return [
        {
            "name": "servers",
            "endpoint": {"path": "/api/servers", "data_selector": "items", "paginator": SinglePagePaginator()},
        },
        {
            "name": endpoint,
            "endpoint": {
                "path": "/api/messages?server={server}",
                "params": messages_params,
                "data_selector": "items",
                # Offset pagination (0-based page + itemsPerPage); an empty page ends the server.
                "paginator": PageNumberPaginator(base_page=0, page_param="page"),
            },
            "include_from_parent": ["id"],
            "data_map": _rename_server,
        },
    ]


def mailosaur_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailosaurResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MAILOSAUR_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MAILOSAUR_BASE_URL,
            "headers": MAILOSAUR_HEADERS,
            # Mailosaur authenticates with the API key as the HTTP Basic auth username and no
            # password. Supplied via the framework auth config so the credential is redacted from
            # logs and raised errors instead of hand-building an Authorization header.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": _build_resources(endpoint, should_use_incremental_field, db_incremental_field_last_value),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework saves AFTER a page is yielded so a crash re-yields the last page (merge
        # dedupes on the primary key) rather than skipping it.
        if state:
            resumable_source_manager.save_state(MailosaurResumeConfig(paginator_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    target = next(resource for resource in resources if resource.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: target,
        primary_keys=config.primary_keys,
        # Messages arrive newest-first and the API exposes no ascending sort, so the watermark
        # (max received) is finalized only at end of sync — see finalize_desc_sort_incremental_value.
        sort_mode="desc" if config.fan_out_over_servers else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=target.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe the account-level `GET /api/servers` endpoint to confirm the key is genuine.

    An account-level key is required to enumerate servers (and therefore to sync any mail);
    a server-scoped key is rejected here, which is the correct signal for this connector.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{MAILOSAUR_BASE_URL}/api/servers",
        headers=MAILOSAUR_HEADERS,
        auth=HTTPBasicAuth(api_key, ""),
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Mailosaur API key"
    if status == 403:
        return False, "This Mailosaur API key cannot list servers. Use an account-level API key."
    if status is None:
        return False, "Could not reach Mailosaur to validate the API key"
    return False, f"Mailosaur API error: {status}"
