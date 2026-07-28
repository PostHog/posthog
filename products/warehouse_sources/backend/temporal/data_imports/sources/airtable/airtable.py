from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import AIRTABLE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

AIRTABLE_BASE_URL = "https://api.airtable.com/v0"
# Record list pages cap at 100.
PAGE_SIZE = 100


def _format_created_time(value: Any) -> str:
    """Format an incremental cursor for an IS_AFTER(CREATED_TIME(), ...) formula (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _created_time_formula(value: Any) -> str:
    return f'IS_AFTER(CREATED_TIME(), "{_format_created_time(value)}")'


def _rename_base_id(table: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent injects the base's id under `_bases_id`; expose it as `_base_id`
    # to keep the emitted table row shape identical to the hand-rolled source.
    base_id = table.pop("_bases_id")
    return {**table, "_base_id": base_id}


def _rename_record_parents(record: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent injects the parent table's `_base_id`/`id` under mangled keys; expose
    # them as `_base_id`/`_table_id` to match the hand-rolled record row shape.
    base_id = record.pop("_tables__base_id")
    table_id = record.pop("_tables_id")
    return {**record, "_base_id": base_id, "_table_id": table_id}


def validate_credentials(personal_access_token: str) -> bool:
    """Confirm the PAT is valid with a cheap one-base meta probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(personal_access_token,)),
        f"{AIRTABLE_BASE_URL}/meta/bases",
        headers={"Authorization": f"Bearer {personal_access_token}"},
    )
    return ok


def _bases_resource() -> dict[str, Any]:
    return {
        "name": "bases",
        "endpoint": {
            "path": "/meta/bases",
            "data_selector": "bases",
            # List-page offsets are cursor tokens returned in the body under `offset`.
            "paginator": JSONResponseCursorPaginator(cursor_path="offset", cursor_param="offset"),
        },
    }


def _tables_resource() -> dict[str, Any]:
    return {
        "name": "tables",
        # Carry the parent base id forward; renamed to `_base_id` by the data_map.
        "include_from_parent": ["id"],
        "endpoint": {
            "path": "/meta/bases/{base_id}/tables",
            "params": {"base_id": {"type": "resolve", "resource": "bases", "field": "id"}},
            "data_selector": "tables",
            # Airtable returns every table for a base in one response.
            "paginator": SinglePagePaginator(),
        },
        "data_map": _rename_base_id,
    }


def _records_resource(db_incremental_field_last_value: Optional[Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "pageSize": PAGE_SIZE,
        # Records fan out over every table of every base — resolve both path params from the
        # same parent table row (base id was injected onto it as `_base_id`).
        "base_id": {"type": "resolve", "resource": "tables", "field": "_base_id"},
        "table_id": {"type": "resolve", "resource": "tables", "field": "id"},
    }
    # createdTime is the only timestamp on record payloads; filter server-side with a formula.
    # Only inject the filter when there's a real cursor value (a full refresh must not filter).
    if db_incremental_field_last_value is not None:
        params["filterByFormula"] = {
            "type": "incremental",
            "cursor_path": "createdTime",
            "convert": _created_time_formula,
        }
    return {
        "name": "records",
        "include_from_parent": ["_base_id", "id"],
        "endpoint": {
            "path": "/{base_id}/{table_id}",
            "params": params,
            "data_selector": "records",
            "paginator": JSONResponseCursorPaginator(cursor_path="offset", cursor_param="offset"),
        },
        "data_map": _rename_record_parents,
    }


# Each endpoint is the leaf of the bases -> tables -> records fan-out chain up to that level.
_ENDPOINT_CHAIN: dict[str, list[str]] = {
    "bases": ["bases"],
    "tables": ["bases", "tables"],
    "records": ["bases", "tables", "records"],
}


def airtable_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AIRTABLE_ENDPOINTS[endpoint]

    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    resource_builders: dict[str, Any] = {
        "bases": _bases_resource,
        "tables": _tables_resource,
        "records": lambda: _records_resource(last_value),
    }
    resources = [resource_builders[name]() for name in _ENDPOINT_CHAIN[endpoint]]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": AIRTABLE_BASE_URL,
            "auth": {"type": "bearer", "token": personal_access_token},
        },
        "resources": resources,
    }

    built = rest_api_resources(rest_config, team_id, job_id, last_value)
    resource: Resource = next(r for r in built if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
