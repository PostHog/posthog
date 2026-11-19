from dataclasses import field
from typing import Any

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    ResponseAction,
    frozen,
)

SELECTSTAR_BASE_URL = "https://api.production.selectstar.com"

# Select Star's DRF-style list endpoints default to 100 rows per page; this is well within
# their documented burst limit (1000 requests/60s) for organizations with large catalogs.
PAGE_SIZE = 100

# A parent deleted between the parent listing and its child fetch 404s; skip it instead of
# failing the whole fan-out.
_SKIP_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


@frozen
class SelectStarEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable "created" field to partition by. None when the response carries no field that
    # never changes after creation (never partition on a field that can be edited later).
    partition_key: str | None = None
    # Set where the resource only exists per parent row (e.g. /v1/lineage/{guid}/).
    fanout: DependentEndpointConfig | None = None
    data_selector: str = "results"
    # False for responses that return the whole collection in one body with no `next` link.
    paginated: bool = True
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


def _fanout(parent_name: str, parent_key: str, child_params: dict[str, Any] | None = None) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param="guid",
        resolve_field="guid",
        include_from_parent=["guid"],
        parent_field_renames={"guid": parent_key},
        parent_params={"page_size": PAGE_SIZE},
        child_params=child_params or {},
        child_response_actions=_SKIP_MISSING_PARENT,
    )


_ENDPOINT_LIST: tuple[SelectStarEndpointConfig, ...] = (
    SelectStarEndpointConfig(
        name="Tables",
        path="/v1/tables/",
        primary_keys=["guid"],
        # Both filters are server-side (`<field>__gte`); the row also carries the field back,
        # so either can drive the watermark. updated_on tracks metadata edits, last_queried_on
        # tracks query activity — the user picks which recency matters to them.
        incremental_fields=[_datetime_field("updated_on"), _datetime_field("last_queried_on")],
        partition_key="db_created_on",
    ),
    SelectStarEndpointConfig(
        name="Columns",
        path="/v1/columns/",
        primary_keys=["guid"],
        # The endpoint accepts an `updated_on__gte` filter, but the Column object itself never
        # returns an `updated_on` (or any other timestamp) field, so there is nothing to read
        # back as a watermark. Full refresh only.
        incremental_fields=[],
    ),
    SelectStarEndpointConfig(
        name="Databases",
        path="/v1/databases/",
        primary_keys=["guid"],
        # Same gap as Columns: `updated_on__gte` filters, but no timestamp comes back on the row.
        incremental_fields=[],
    ),
    SelectStarEndpointConfig(
        name="Schemas",
        path="/v1/schemas/",
        primary_keys=["guid"],
        incremental_fields=[],
    ),
    SelectStarEndpointConfig(
        name="Tags",
        path="/v1/tags/",
        primary_keys=["guid"],
        incremental_fields=[_datetime_field("updated_on")],
    ),
    SelectStarEndpointConfig(
        name="Dashboards",
        path="/v1/bi/dashboards/",
        primary_keys=["guid"],
        # No `updated_on`-style filter param on this endpoint, so full refresh only.
        incremental_fields=[],
        partition_key="dashboard_created_at",
    ),
    SelectStarEndpointConfig(
        name="Lineage",
        path="/v1/lineage/{guid}/",
        # Each table's response lists the table itself plus its direct downstream objects, so an
        # object appears once per upstream table: the root table is part of the key.
        primary_keys=["table_guid", "key"],
        fanout=_fanout("Tables", "table_guid", {"max_depth": "1", "direction": "right", "mode": "table"}),
        data_selector="table_lineage",
        paginated=False,
    ),
    SelectStarEndpointConfig(
        name="DashboardFrequentUsers",
        path="/v1/bi/dashboards/{guid}/frequent-dsusers/",
        primary_keys=["dashboard_guid", "guid"],
        fanout=_fanout("Dashboards", "dashboard_guid"),
    ),
    SelectStarEndpointConfig(
        name="TaggedItems",
        path="/v1/tags/items/{guid}/",
        # One asset can carry the same tag as both a user-defined and a suggested tag.
        primary_keys=["tag_guid", "kind", "item_guid"],
        fanout=_fanout("Tags", "tag_guid"),
    ),
)

SELECTSTAR_ENDPOINTS: dict[str, SelectStarEndpointConfig] = {config.name: config for config in _ENDPOINT_LIST}

ENDPOINTS = tuple(SELECTSTAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SELECTSTAR_ENDPOINTS.items()
}
