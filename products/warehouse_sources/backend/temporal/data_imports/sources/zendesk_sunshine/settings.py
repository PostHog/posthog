from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Catalog endpoints (object types, relationship types, limits) are small; a conservative
# page size keeps responses light.
DEFAULT_PAGE_SIZE = 100
# Record endpoints (`objects/records`, `relationships/records`, `objects/query`) document
# `per_page` from 1 to 1000.
RECORDS_PAGE_SIZE = 1000

# The legacy custom objects search endpoint — the only Sunshine endpoint with a server-side
# `_updated_at` range filter, so incremental object record syncs go through it.
QUERY_PATH = "objects/query"
# The query endpoint's pagination cursor grows with every page and Zendesk documents a hard
# limit of ~80 pages (the cursor exceeds the 4096-char URI limit), so re-window the
# `_updated_at` range well before that.
MAX_PAGES_PER_QUERY_WINDOW = 75
# `_updated_at`/`_created_at` range filters expect `yyyy-MM-dd HH:mm:ss.SSS`.
DEFAULT_QUERY_WINDOW_START = "1970-01-01 00:00:00.000"


@dataclass(frozen=True)
class ZendeskSunshineEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    page_size: int = DEFAULT_PAGE_SIZE
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Single-hop fan-out: iterate `fanout_parent` and bind `resolve_field` from each parent
    # row into the `{resolve_placeholder}` in `path`.
    fanout_parent: str | None = None
    resolve_placeholder: str | None = None
    resolve_field: str | None = None
    include_from_parent: list[str] = field(default_factory=list)
    parent_field_renames: dict[str, str] = field(default_factory=dict)
    single_page: bool = False


ZENDESK_SUNSHINE_ENDPOINTS: dict[str, ZendeskSunshineEndpointConfig] = {
    "object_types": ZendeskSunshineEndpointConfig(
        name="object_types",
        path="objects/types",
        primary_keys=["key"],
        partition_key="created_at",
    ),
    "object_records": ZendeskSunshineEndpointConfig(
        name="object_records",
        # Full-refresh path. Incremental syncs go through QUERY_PATH instead — the list
        # endpoint has no server-side timestamp filter.
        path="objects/records?type={object_type}",
        primary_keys=["id"],
        page_size=RECORDS_PAGE_SIZE,
        partition_key="created_at",
        incremental_fields=[incremental_field("updated_at")],
        fanout_parent="object_types",
        resolve_placeholder="object_type",
        resolve_field="key",
    ),
    "object_type_policies": ZendeskSunshineEndpointConfig(
        name="object_type_policies",
        path="objects/types/{object_type}/permissions",
        # The permissions endpoint returns one policy object per object type; the parent key
        # is injected as `object_type` so it doubles as the row's identity.
        primary_keys=["object_type"],
        fanout_parent="object_types",
        resolve_placeholder="object_type",
        resolve_field="key",
        include_from_parent=["key"],
        parent_field_renames={"key": "object_type"},
        single_page=True,
    ),
    "relationship_types": ZendeskSunshineEndpointConfig(
        name="relationship_types",
        path="relationships/types",
        primary_keys=["key"],
        partition_key="created_at",
    ),
    "relationship_records": ZendeskSunshineEndpointConfig(
        name="relationship_records",
        path="relationships/records?type={relationship_type}",
        primary_keys=["id"],
        page_size=RECORDS_PAGE_SIZE,
        partition_key="created_at",
        fanout_parent="relationship_types",
        resolve_placeholder="relationship_type",
        resolve_field="key",
    ),
    "limits": ZendeskSunshineEndpointConfig(
        name="limits",
        path="limits",
        primary_keys=["key"],
    ),
}

ENDPOINTS = tuple(ZENDESK_SUNSHINE_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ZENDESK_SUNSHINE_ENDPOINTS.items()
}
