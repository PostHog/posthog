from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# v1 is the legacy Sunshine custom objects API (`/api/sunshine/`, no version token). v2 is the
# current custom objects API under the standard Support API (`/api/v2/custom_objects`). Zendesk is
# retiring the legacy API (no new legacy objects after 2026-01-15, removed 2026-06-30), so new
# sources default to v2; existing sources stay on their pin until a human migrates them.
ZENDESK_SUNSHINE_V1 = UNVERSIONED_API_VERSION
ZENDESK_SUNSHINE_V2 = "v2"

# Per-version base path segment appended to `https://{subdomain}.zendesk.com/`.
BASE_PATH_BY_VERSION = {ZENDESK_SUNSHINE_V1: "api/sunshine/", ZENDESK_SUNSHINE_V2: "api/v2/"}

# Catalog endpoints (object types, relationship types, limits) are small; a conservative
# page size keeps responses light.
DEFAULT_PAGE_SIZE = 100
# Record endpoints (`objects/records`, `relationships/records`, `objects/query`) document
# `per_page` from 1 to 1000.
RECORDS_PAGE_SIZE = 1000
# The v2 custom object records list caps `per_page` at 100.
RECORDS_PAGE_SIZE_V2 = 100

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
    # JSON key holding the row array in the response envelope. v1 Sunshine wraps everything in
    # `data`; v2 uses a per-resource key (`custom_objects`, `custom_object_records`, ...).
    data_selector: str = "data"
    # Extra static query params merged into the list request (e.g. v2 records `sort=updated_at`).
    extra_params: dict[str, Any] = field(default_factory=dict)


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

# v2 custom objects API. The legacy relationship and permission-policy resources have no v2
# equivalent, and the record shape differs (fields nest under `custom_object_fields` rather than a
# flat `attributes`), so the v2 table set is deliberately different from v1 — this is why repinning
# an existing source is a lossy transform rather than an in-place `api_version` flip. The v2 records
# list endpoint has no server-side `updated_at` filter (only `filter[ids]`/`filter[external_ids]`),
# so records sync as full refresh sorted by `updated_at`.
ZENDESK_SUNSHINE_V2_ENDPOINTS: dict[str, ZendeskSunshineEndpointConfig] = {
    "custom_objects": ZendeskSunshineEndpointConfig(
        name="custom_objects",
        path="custom_objects",
        primary_keys=["key"],
        partition_key="created_at",
        data_selector="custom_objects",
    ),
    "custom_object_records": ZendeskSunshineEndpointConfig(
        name="custom_object_records",
        path="custom_objects/{custom_object_key}/records",
        primary_keys=["id"],
        page_size=RECORDS_PAGE_SIZE_V2,
        partition_key="created_at",
        data_selector="custom_object_records",
        extra_params={"sort": "updated_at"},
        fanout_parent="custom_objects",
        resolve_placeholder="custom_object_key",
        resolve_field="key",
    ),
    "custom_object_fields": ZendeskSunshineEndpointConfig(
        name="custom_object_fields",
        path="custom_objects/{custom_object_key}/fields",
        primary_keys=["id"],
        page_size=RECORDS_PAGE_SIZE_V2,
        data_selector="custom_object_fields",
        fanout_parent="custom_objects",
        resolve_placeholder="custom_object_key",
        resolve_field="key",
    ),
}

V2_ENDPOINTS = tuple(ZENDESK_SUNSHINE_V2_ENDPOINTS)

ENDPOINTS_BY_VERSION: dict[str, dict[str, ZendeskSunshineEndpointConfig]] = {
    ZENDESK_SUNSHINE_V1: ZENDESK_SUNSHINE_ENDPOINTS,
    ZENDESK_SUNSHINE_V2: ZENDESK_SUNSHINE_V2_ENDPOINTS,
}

INCREMENTAL_FIELDS_BY_VERSION: dict[str, dict[str, list[IncrementalField]]] = {
    version: {name: config.incremental_fields for name, config in endpoints.items()}
    for version, endpoints in ENDPOINTS_BY_VERSION.items()
}

# Endpoints offered as merge-incremental (never append) per version. The v1 object records query
# filter is inclusive on its lower bound, so boundary rows re-fetch every sync and only merge
# dedupes them; v2 has no incremental records, so nothing to declare.
MERGE_ONLY_BY_VERSION: dict[str, tuple[str, ...]] = {
    ZENDESK_SUNSHINE_V1: ("object_records",),
    ZENDESK_SUNSHINE_V2: (),
}


def endpoints_for_version(api_version: str) -> dict[str, ZendeskSunshineEndpointConfig]:
    try:
        return ENDPOINTS_BY_VERSION[api_version]
    except KeyError as e:
        raise ValueError(f"Unsupported Zendesk Sunshine API version: {api_version!r}") from e
