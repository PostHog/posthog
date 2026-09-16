from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

SELECTSTAR_BASE_URL = "https://api.production.selectstar.com"

# Select Star's DRF-style list endpoints default to 100 rows per page; this is well within
# their documented burst limit (1000 requests/60s) for organizations with large catalogs.
PAGE_SIZE = 100


@frozen
class SelectStarEndpointConfig:
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable "created" field to partition by. None when the response carries no field that
    # never changes after creation (never partition on a field that can be edited later).
    partition_key: str | None = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


SELECTSTAR_ENDPOINTS: dict[str, SelectStarEndpointConfig] = {
    "Tables": SelectStarEndpointConfig(
        path="/v1/tables/",
        primary_keys=["guid"],
        # Both filters are server-side (`<field>__gte`); the row also carries the field back,
        # so either can drive the watermark. updated_on tracks metadata edits, last_queried_on
        # tracks query activity — the user picks which recency matters to them.
        incremental_fields=[_datetime_field("updated_on"), _datetime_field("last_queried_on")],
        partition_key="db_created_on",
    ),
    "Columns": SelectStarEndpointConfig(
        path="/v1/columns/",
        primary_keys=["guid"],
        # The endpoint accepts an `updated_on__gte` filter, but the Column object itself never
        # returns an `updated_on` (or any other timestamp) field, so there is nothing to read
        # back as a watermark. Full refresh only.
        incremental_fields=[],
    ),
    "Databases": SelectStarEndpointConfig(
        path="/v1/databases/",
        primary_keys=["guid"],
        # Same gap as Columns: `updated_on__gte` filters, but no timestamp comes back on the row.
        incremental_fields=[],
    ),
    "Schemas": SelectStarEndpointConfig(
        path="/v1/schemas/",
        primary_keys=["guid"],
        incremental_fields=[],
    ),
    "Tags": SelectStarEndpointConfig(
        path="/v1/tags/",
        primary_keys=["guid"],
        incremental_fields=[_datetime_field("updated_on")],
    ),
    "Dashboards": SelectStarEndpointConfig(
        path="/v1/bi/dashboards/",
        primary_keys=["guid"],
        # No `updated_on`-style filter param on this endpoint, so full refresh only.
        incremental_fields=[],
        partition_key="dashboard_created_at",
    ),
}

ENDPOINTS = tuple(SELECTSTAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SELECTSTAR_ENDPOINTS.items()
}
