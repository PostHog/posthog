import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    CONTACT_STATUSES,
    EMAILOCTOPUS_ENDPOINTS,
    EmailOctopusEndpointConfig,
)

EMAILOCTOPUS_BASE_URL = "https://api.emailoctopus.com"
# The v2 API caps a page at 100 results.
PAGE_SIZE = 100
# EmailOctopus returns the next page as a full URL under `paging.next.url`; the paginator follows it
# verbatim so the original query string (including any incremental filter) is preserved across pages.
_NEXT_URL_PATH = "paging.next.url"
# Only non-secret headers here — the Bearer token rides on the framework `auth` config so it's
# redacted from logged URLs and raised error messages.
_HEADERS = {"Accept": "application/json"}

# EmailOctopus serves every API version from the same host with the same resource paths, bearer
# auth, and cursor pagination — the version isn't carried in the request (no path segment, header,
# or query param). Both supported labels therefore resolve to the one REST host the source has
# always used; the seam exists so a genuinely divergent future version can branch here, and pinned
# instances keep hitting the same host regardless of the default.
_BASE_URL_BY_VERSION = {
    "v1": EMAILOCTOPUS_BASE_URL,
    "v2": EMAILOCTOPUS_BASE_URL,
}


def _base_url_for_version(api_version: str) -> str:
    return _BASE_URL_BY_VERSION.get(api_version, EMAILOCTOPUS_BASE_URL)


@dataclasses.dataclass
class EmailOctopusResumeConfig:
    # Full next-page URL returned by the API (`paging.next.url`). Followed verbatim so the original
    # query string — including any incremental time filter — is preserved across a resume. None means
    # "start this list at its first page".
    next_url: str | None = None
    # Legacy fan-out bookmark fields. The contacts fan-out is now a composed set of single-hop
    # dependent resources whose retries re-fetch (the [list_id, id] merge key dedupes), so these are
    # no longer written. They are kept — with defaults — so any state persisted by the previous
    # implementation still deserializes via ``dataclass(**saved)`` on resume.
    list_id: str | None = None
    status: str | None = None
    incremental_field: str | None = None
    filter_value: str | None = None


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for EmailOctopus's ISO 8601 filters (e.g. 2024-01-19T12:14:28Z)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_contact_params(status: str, incremental_field: str | None, filter_value: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "status": status}
    if incremental_field and filter_value:
        # Server-side incremental filter, e.g. last_updated_at.gte=2024-01-19T12:14:28Z.
        params[f"{incremental_field}.gte"] = filter_value
    return params


def validate_credentials(api_key: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{EMAILOCTOPUS_BASE_URL}/lists?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_HEADERS},
    )
    return ok


def _client_config(api_key: str, base_url: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "headers": _HEADERS,
        "auth": {"type": "bearer", "token": api_key},
    }


def _rename_list_id(row: dict[str, Any]) -> dict[str, Any]:
    # `include_from_parent=["id"]` injects the parent list's id as `_lists_id`; expose it as `list_id`
    # so contact rows carry the exact same field the previous implementation attached.
    if "_lists_id" in row:
        row["list_id"] = row.pop("_lists_id")
    return row


def _top_level_resource(
    api_key: str,
    base_url: str,
    config: EmailOctopusEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[EmailOctopusResumeConfig],
) -> Any:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, base_url),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                    "paginator": JSONResponsePaginator(next_url_path=_NEXT_URL_PATH),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            manager.save_state(EmailOctopusResumeConfig(next_url=str(state["next_url"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _contacts_items(
    api_key: str,
    base_url: str,
    config: EmailOctopusEndpointConfig,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every list and contact status, attaching each contact's `list_id`.

    Contacts are nested under lists and the API returns one status at a time, so each status is its
    own single-hop parent(lists)->child(contacts) fan-out; the results are concatenated. A list
    deleted between enumeration and the child fetch 404s, which is ignored per (list, status) via
    `response_actions` rather than failing the whole sync. The [list_id, id] merge key keeps a single
    row per contact across statuses and dedupes any rows re-fetched on a retry.
    """
    filter_field = incremental_field if should_use_incremental_field else None
    filter_value = (
        _format_incremental_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value and incremental_field
        else None
    )

    for status in CONTACT_STATUSES:
        contact_params: dict[str, Any] = {
            "list_id": {"type": "resolve", "resource": "lists", "field": "id"},
            **_build_contact_params(status, filter_field, filter_value),
        }
        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key, base_url),
            "resource_defaults": {},
            "resources": [
                {
                    "name": "lists",
                    "endpoint": {
                        "path": "/lists",
                        "params": {"limit": PAGE_SIZE},
                        "data_selector": "data",
                        "paginator": JSONResponsePaginator(next_url_path=_NEXT_URL_PATH),
                    },
                },
                {
                    "name": f"contacts_{status}",
                    "include_from_parent": ["id"],
                    "endpoint": {
                        "path": config.path,
                        "params": contact_params,
                        "data_selector": "data",
                        "paginator": JSONResponsePaginator(next_url_path=_NEXT_URL_PATH),
                        # A list deleted mid-fan-out 404s; treat it as an empty result for this
                        # (list, status) and move on instead of failing the sync.
                        "response_actions": [{"status_code": 404, "action": "ignore"}],
                    },
                },
            ],
        }

        resources = rest_api_resources(rest_config, team_id, job_id, None)
        child = next(r for r in resources if getattr(r, "name", None) == f"contacts_{status}")
        child.add_map(_rename_list_id)
        yield from child


def emailoctopus_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EmailOctopusResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = EMAILOCTOPUS_ENDPOINTS[endpoint]
    base_url = _base_url_for_version(api_version)

    if endpoint_config.fan_out_over_lists:
        items: Any = lambda: _contacts_items(
            api_key,
            base_url,
            endpoint_config,
            team_id,
            job_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    else:
        resource = _top_level_resource(api_key, base_url, endpoint_config, team_id, job_id, resumable_source_manager)
        items = lambda: resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # The v2 contacts endpoint paginates with an opaque cursor and does not document an ascending
        # sort guarantee. "asc" is the safe default: the incremental fields are monotonic wall-clock
        # timestamps, and the resumable cursor (not the watermark) drives mid-sync continuation.
        sort_mode="asc",
    )
