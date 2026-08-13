"""Transport for the Leadfeeder (Dealfront) data warehouse source.

The source implements two vendor API generations, both served from https://api.leadfeeder.com, and
dispatches between them on the resolved API-version pin:

- LEADFEEDER_API_LEGACY ("v1") — the legacy API, `Authorization: Token token=<token>`, JSON:API
  page-number pagination (`page[number]`) with a `links.next` cursor, account-scoped
  `/accounts/{id}/leads|visits` paths and a server-side `start_date`/`end_date` filter. The shape
  Airbyte's connector targets and the label existing source rows are pinned to. The vendor has
  deprecated it (maintenance-only, no new tokens issued) but still serves it, with no announced sunset.

- LEADFEEDER_API_2026_08_07 — the unified Dealfront API, `X-Api-Key` on `/v1/*`, page-number
  pagination via `page[num]` with a `meta.page_count` stop. The only generation new customers can
  obtain credentials for, so it is the default for newly created sources. Its request layer (auth,
  base paths, method, pagination) is dispatched here; row shapes reuse the version-independent
  JSON:API flatten. Both come from the public OpenAPI spec (info.version 2026-08-07, marked
  "work in progress") and warrant live verification before the source leaves alpha.
"""

import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    LEADFEEDER_API_2026_08_07,
    LEADFEEDER_API_LEGACY,
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


# --- Unified Dealfront API (X-Api-Key on /v1/*) --------------------------------------------------


def _unified_headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json", "User-Agent": "PostHog"}


def _unified_base_params() -> dict[str, Any]:
    # The unified API paginates by page number under `page[num]`; the paginator advances page[num]
    # and stops at the last page reported in `meta.page_count`.
    return {"page[size]": PAGE_SIZE}


def _unified_client_config(api_key: str) -> ClientConfig:
    # Auth via the framework api_key config so the key is redacted from any raised error; only the
    # non-secret Accept/User-Agent headers are set on the client. Pin the request to the base host
    # (allowed_hosts=[]) and disable redirects so the credentialed request can't be replayed off-origin.
    return {
        "base_url": LEADFEEDER_BASE_URL,
        "auth": {
            "type": "api_key",
            "api_key": api_key,
            "name": "X-Api-Key",
            "location": "header",
        },
        "headers": {"Accept": "application/json", "User-Agent": "PostHog"},
        "paginator": PageNumberPaginator(base_page=1, page_param="page[num]", total_path="meta.page_count"),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _unified_single_resource(
    client: ClientConfig,
    name: str,
    endpoint: Endpoint,
    team_id: int,
    job_id: str,
    data_map: Any,
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [{"name": name, "endpoint": endpoint, "data_map": data_map}],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _unified_accounts_endpoint() -> Endpoint:
    # /v1/accounts returns its whole result set in one unpaginated, non-empty response with no
    # `meta.page_count` field. The client-level PageNumberPaginator's total-pages stop check silently
    # no-ops when that field is absent (it falls through to "has next page"), and `stop_after_empty_page`
    # never fires either since the page is never empty — so without this override, a sync would keep
    # requesting page[num]=2, 3, ... forever. Override with a page-number paginator capped at one page
    # via `maximum_page`: it still requests `page[num]=1` like every other unified endpoint (so a vendor
    # response that *does* start paginating accounts one day is requested consistently), but the
    # `maximum_page=1` cap makes it stop after that one request no matter what the body contains —
    # accounts is a small dimension table (see LEADFEEDER_ENDPOINTS), so a single page is authoritative.
    accounts_config = LEADFEEDER_ENDPOINTS[_ACCOUNTS_RESOURCE]
    return {
        "path": accounts_config.unified_path,
        "params": _unified_base_params(),
        "data_selector": "data",
        "paginator": PageNumberPaginator(base_page=1, page_param="page[num]", maximum_page=1),
    }


def _unified_account_ids(client: ClientConfig, team_id: int, job_id: str) -> Iterator[str]:
    resource = _unified_single_resource(
        client,
        _ACCOUNTS_RESOURCE,
        _unified_accounts_endpoint(),
        team_id,
        job_id,
        _flatten_top_level,
    )
    for page in resource:
        for row in page:
            account_id = row.get("id")
            if account_id is not None:
                yield str(account_id)


def _unified_leadfeeder_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    start_date_config: str = "",
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LEADFEEDER_ENDPOINTS[endpoint]
    client = _unified_client_config(api_key)

    if not config.fan_out_over_accounts:
        # Accounts needs its own bounded paginator (see _unified_accounts_endpoint); other non-fan-out
        # endpoints, if any are added later, keep the client-level page_count-driven paginator.
        single_endpoint: Endpoint = (
            _unified_accounts_endpoint()
            if endpoint == _ACCOUNTS_RESOURCE
            else {"path": config.unified_path, "params": _unified_base_params(), "data_selector": "data"}
        )
        resource = _unified_single_resource(
            client,
            endpoint,
            single_endpoint,
            team_id,
            job_id,
            _flatten_top_level,
        )
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
        )

    # The unified fan-out endpoints take `account_id` as a query param, which the shared REST
    # framework can't resolve from a parent resource (it only binds resolved params into the path),
    # so iterate accounts explicitly and sync each account's window with the id baked in. The date
    # range is computed from the incremental watermark (if any) or the configured start date;
    # re-reading the floored day is self-healing since merge dedupes on the primary key.
    start = (
        _to_date_str(db_incremental_field_last_value)
        if db_incremental_field_last_value is not None
        else _default_start_date(start_date_config)
    )
    end = datetime.now(UTC).date().isoformat()

    def _fanned() -> Iterator[list[dict[str, Any]]]:
        for account_id in _unified_account_ids(client, team_id, job_id):
            child_params: dict[str, Any] = {**_unified_base_params(), "account_id": account_id}
            child_endpoint: Endpoint = {
                "path": config.unified_path,
                "params": child_params,
                "data_selector": "data",
            }
            if config.unified_method == "POST":
                # Web visits are a POST search whose date window lives in the body, not the query string.
                child_endpoint["method"] = "POST"
                child_endpoint["json"] = {"start_date": start, "end_date": end}
            else:
                child_params["start_date"] = start
                child_params["end_date"] = end
            yield from _unified_single_resource(
                client, endpoint, child_endpoint, team_id, job_id, partial(_flatten_item, account_id=account_id)
            )

    # Partition only on a field confirmed present in the unified schema (visits' `started_at`). The
    # visitor-companies rows carry no confirmed top-level date, so leads sync unpartitioned here.
    partition_key = config.partition_key if endpoint == "visits" else None
    return SourceResponse(
        name=endpoint,
        items=_fanned,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


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
    api_version: str = LEADFEEDER_API_LEGACY,
) -> SourceResponse:
    if api_version == LEADFEEDER_API_2026_08_07:
        return _unified_leadfeeder_source(
            api_key=api_token,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            start_date_config=start_date_config,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

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


def validate_credentials(api_token: str, api_version: str = LEADFEEDER_API_LEGACY) -> bool:
    # Probe the accounts list under the pinned generation: the legacy API takes an
    # `Authorization: Token token=...` header, the unified API an `X-Api-Key` header on `/v1/accounts`.
    # Both credentials ride in headers the denylist can't see, so register the value for redaction and
    # block redirects so the probe can't resend it off-origin.
    if api_version == LEADFEEDER_API_2026_08_07:
        url = f"{LEADFEEDER_BASE_URL}/v1/accounts"
        headers = _unified_headers(api_token)
    else:
        url = f"{LEADFEEDER_BASE_URL}/accounts"
        headers = _get_headers(api_token)
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        url,
        headers=headers,
    )
    return ok
