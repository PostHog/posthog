"""Transport for the Leadfeeder (Dealfront) data warehouse source.

Targets the legacy Leadfeeder API at https://api.leadfeeder.com, authenticated with the
`Authorization: Token token=<token>` header. This generation exposes the well-documented
accounts / leads / visits streams with JSON:API page-number pagination and a server-side
`start_date`/`end_date` date-range filter — the same shape Airbyte's connector targets.

Leadfeeder also ships a newer API-first generation (`X-Api-Key` auth on `/v1/*`, Companies &
Contacts, web-visits/search). Its stream shapes could not be verified against the live API without
credentials, so this source deliberately implements the stable legacy generation and ships as an
unreleased alpha. Endpoint/field names below come from the public legacy API reference; if the live
API differs they may need adjustment.
"""

import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    LEADFEEDER_ENDPOINTS,
    LeadfeederEndpointConfig,
)

LEADFEEDER_BASE_URL = "https://api.leadfeeder.com"
PAGE_SIZE = 100  # JSON:API page[size] max is 100 (default 10)
DEFAULT_LOOKBACK_DAYS = 365  # First-sync window when the user leaves start_date blank

# Name the accounts fan-out parent uses; the framework injects the parent id into child rows under
# `_accounts_id` (see make_parent_key_name), which the child data_map renames to `account_id`.
_ACCOUNTS_RESOURCE = "accounts"
_PARENT_ID_KEY = f"_{_ACCOUNTS_RESOURCE}_id"


@dataclasses.dataclass
class LeadfeederResumeConfig:
    # The account currently being paginated — retained so an old saved state (written before the
    # rest_source migration) still parses via `dataclass(**saved)`. New fan-out runs persist the
    # framework's dependent-resource checkpoint under `fanout_state` instead.
    account_id: str | None = None
    # Full next-page URL (from the API's `links.next`) to resume a top-level endpoint from.
    next_url: str | None = None
    # Framework dependent-resource checkpoint for fan-out endpoints (leads/visits):
    # `{"completed": [...], "current": path | None, "child_state": {...} | None}`.
    fanout_state: Optional[dict[str, Any]] = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_token}",
        "Accept": "application/json",
        # Leadfeeder asks integrations to identify themselves via User-Agent.
        "User-Agent": "PostHog",
    }


def _flatten_item(item: dict[str, Any], account_id: str | None) -> dict[str, Any]:
    """Flatten a JSON:API resource object into a single flat row.

    JSON:API items look like `{"id", "type", "attributes": {...}}`; we lift `attributes` to the root
    and keep `id`/`type`. Fan-out rows also carry the parent `account_id` so the composite primary key
    stays unique across every account.
    """
    # `id` is the primary key, so read it directly: a malformed item without one should fail loudly
    # rather than seed a row under a `None` key that later merges multi-match or duplicate.
    row: dict[str, Any] = {"id": item["id"], "type": item.get("type")}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        row.update(attributes)
    if account_id is not None:
        row["account_id"] = account_id
    return row


def _flatten_top_level(item: dict[str, Any]) -> dict[str, Any]:
    return _flatten_item(item, account_id=None)


def _flatten_fan_out(item: dict[str, Any]) -> dict[str, Any]:
    # The framework merges the parent account id into the raw item under `_accounts_id`; move it to
    # `account_id` (and drop the framework's key) so the row shape matches the hand-rolled source.
    account_id = item.get(_PARENT_ID_KEY)
    row = _flatten_item(item, account_id=str(account_id) if account_id is not None else None)
    return row


def _to_date_str(value: Any) -> str:
    """Coerce a date / datetime / ISO string incremental value to a yyyy-mm-dd string.

    Leadfeeder's start_date/end_date filter is day-granular, so a datetime cursor (e.g. a visit's
    `started_at`) is floored to its date. Re-querying from the floored day re-reads that whole day,
    which merge dedupes on the primary key — so the incremental sync is self-healing even though the
    filter is coarser than the cursor.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _default_start_date(start_date_config: str) -> str:
    """Resolve the start_date used when there is no incremental watermark to resume from."""
    if start_date_config:
        return _to_date_str(start_date_config)
    return (datetime.now(UTC).date() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


def _client_config(api_token: str) -> ClientConfig:
    # Auth is supplied via the framework api_key config so the token value is redacted from any raised
    # error message; only the non-secret Accept/User-Agent headers are set on the client. Pinning the
    # request to `api.leadfeeder.com` (allowed_hosts=[] means base-host only) and disabling redirects
    # keeps the credentialed request from being resent to another host via a spoofed next link or 3xx.
    return {
        "base_url": LEADFEEDER_BASE_URL,
        "auth": {
            "type": "api_key",
            "api_key": f"Token token={api_token}",
            "name": "Authorization",
            "location": "header",
        },
        "headers": {"Accept": "application/json", "User-Agent": "PostHog"},
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _date_range_incremental(config: LeadfeederEndpointConfig, start_date_config: str) -> IncrementalConfig:
    """Server-side start_date/end_date window the leads/visits endpoints require.

    `initial_value` is the fallback start when there is no watermark (full-refresh, or the first
    incremental sync); `end_value` is always today. Both — and any incoming watermark — are floored to
    a yyyy-mm-dd string by `convert`, matching the hand-rolled `_compute_date_range`.
    """
    cursor_field = config.incremental_fields[0]["field"] if config.incremental_fields else ""
    return {
        "cursor_path": cursor_field,
        "start_param": "start_date",
        "end_param": "end_date",
        "initial_value": _default_start_date(start_date_config),
        "end_value": datetime.now(UTC).date().isoformat(),
        "convert": _to_date_str,
    }


def _base_params() -> dict[str, Any]:
    return {"page[number]": 1, "page[size]": PAGE_SIZE}


def leadfeeder_source(
    api_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[LeadfeederResumeConfig],
    team_id: int,
    job_id: str,
    start_date_config: str = "",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = LEADFEEDER_ENDPOINTS[endpoint]
    fan_out = config.fan_out_over_accounts

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None:
        if fan_out:
            # An old-shape fan-out state (account_id/next_url, no fanout_state) can't seed the
            # framework checkpoint, so start that part fresh — retries re-fetch and merge dedupes.
            initial_paginator_state = resume.fanout_state
        elif resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes on PK).
        if not state:
            return
        if fan_out:
            resumable_source_manager.save_state(LeadfeederResumeConfig(fanout_state=state))
        elif state.get("next_url"):
            resumable_source_manager.save_state(LeadfeederResumeConfig(next_url=state["next_url"]))

    client = _client_config(api_token)

    resource: Resource
    if not fan_out:
        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": _base_params(),
                        "data_selector": "data",
                    },
                    "data_map": _flatten_top_level,
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
    else:
        child_params: dict[str, Any] = {
            **_base_params(),
            "account_id": {"type": "resolve", "resource": _ACCOUNTS_RESOURCE, "field": "id"},
        }
        resources: list[str | EndpointResource] = [
            {
                "name": _ACCOUNTS_RESOURCE,
                "endpoint": {"path": "/accounts", "params": _base_params(), "data_selector": "data"},
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": child_params,
                    "data_selector": "data",
                    "incremental": _date_range_incremental(config, start_date_config),
                },
                "include_from_parent": ["id"],
                "data_map": _flatten_fan_out,
            },
        ]
        rest_config = {"client": client, "resources": resources}
        built = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        resource = next(r for r in built if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> bool:
    # The token rides in a custom `Authorization: Token token=...` header the denylist can't see, so
    # register it for value-based redaction; block redirects so the probe can't resend it off-origin.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        f"{LEADFEEDER_BASE_URL}/accounts",
        headers=_get_headers(api_token),
    )
    return ok
