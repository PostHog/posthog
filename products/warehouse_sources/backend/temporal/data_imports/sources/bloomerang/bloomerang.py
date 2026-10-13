from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.settings import (
    BLOOMERANG_ENDPOINTS,
    PAGE_SIZE,
    BloomerangEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BASE_URL = "https://api.bloomerang.co/v2"


@frozen
class BloomerangResumeConfig:
    # Next `skip` value to resume from. Matches OffsetPaginator's own resume-state shape.
    next_offset: int


def _flatten_audit_trail(item: dict[str, Any]) -> dict[str, Any]:
    """Promote AuditTrail.CreatedDate/LastModifiedDate onto the row root.

    Constituents, Transactions, and Interactions nest their timestamps under an `AuditTrail`
    object; flattening them makes `CreatedDate` usable as a partition key and `LastModifiedDate`
    usable as the incremental cursor column.
    """
    audit_trail = item.pop("AuditTrail", None)
    if isinstance(audit_trail, dict):
        item["CreatedDate"] = audit_trail.get("CreatedDate")
        item["LastModifiedDate"] = audit_trail.get("LastModifiedDate")
    return item


def _format_last_modified(value: Any) -> str:
    """Format an incremental cursor as the ISO-8601 UTC string Bloomerang's `lastModified` filter expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_params(
    config: BloomerangEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        return {
            "lastModified": _format_last_modified(db_incremental_field_last_value),
            "orderBy": "LastModifiedDate",
            "orderDirection": "Asc",
        }
    if config.supports_sort:
        # Explicit stable sort even for full refresh: Bloomerang's own default order direction
        # varies by endpoint (Transactions defaults to Desc), so an unstated default can't be
        # relied on to keep page boundaries stable as rows are inserted mid-sync.
        return {"orderBy": "Id", "orderDirection": "Asc"}
    return {}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "X-Api-Key", "api_key": api_key, "location": "header"},
        # `capture=False`: Constituents, Transactions, and Interactions carry donor PII and
        # free-form interaction notes that the name-based sample scrubbers can't recognise, so
        # keep every response body out of HTTP sample storage. Requests stay metered and logged.
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
        # `X-Api-Key` isn't the standard Authorization header, which `requests` strips on a
        # cross-origin redirect, so a hostile redirect could otherwise harvest it — disable
        # redirects for production syncs the same way the credential probe below already does.
        "allow_redirects": False,
        "paginator": OffsetPaginator(
            limit=PAGE_SIZE,
            offset_param="skip",
            limit_param="take",
            # TotalFiltered reflects whatever filters we send (e.g. lastModified); it equals the
            # unfiltered Total when we send none.
            total_path="TotalFiltered",
        ),
    }


def bloomerang_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BloomerangResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BLOOMERANG_ENDPOINTS[endpoint]
    is_incremental = config.supports_incremental and should_use_incremental_field

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {
            "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint.lower(),
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    "data_selector": "Results",
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion, and saving after the page is yielded means a crash re-yields (merge dedupes)
        # rather than skips it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(BloomerangResumeConfig(next_offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    if config.has_audit_trail:
        resource = resource.add_map(_flatten_audit_trail)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        # `capture=False`: the probe hits `/constituents`, which returns the same donor record
        # shape as the real sync — keep it out of HTTP sample storage too.
        lambda: make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,), capture=False),
        f"{BASE_URL}/constituents",
        headers={"X-Api-Key": api_key},
        # X-Api-Key isn't the standard Authorization header, which `requests` strips on a
        # cross-origin redirect; disable redirects so a hostile redirect can't harvest it.
        allow_redirects=False,
        ok_statuses=(200,),
    )
