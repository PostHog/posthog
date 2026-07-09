from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# OnePageCRM timestamps are ISO 8601 strings (e.g. "2018-05-16T11:52:09Z"); the `modified_since`
# list filter accepts a UNIX timestamp and returns only resources modified since that time.
MODIFIED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "modified_at",
    "type": IncrementalFieldType.DateTime,
    "field": "modified_at",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class OnepagecrmEndpointConfig:
    name: str
    path: str
    # Key the record list is nested under in the response's `data` object (e.g.
    # {"data": {"contacts": [...]}}). None means `data` itself is the list (users, statuses,
    # lead_sources).
    data_key: Optional[str]
    # Singular key each record is wrapped under (e.g. {"contact": {...}}); None if records are
    # returned unwrapped (lead_sources).
    item_key: Optional[str]
    # OnePageCRM object IDs are BSON ids unique across the account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether the endpoint accepts page/per_page params. Config endpoints (users, statuses,
    # lead_sources) return the full list in one response.
    paginated: bool = True
    # Whether the endpoint accepts sort_by/order params (every sortable endpoint here allows both
    # created_at and modified_at).
    supports_sort: bool = False
    # Non-empty only where the API exposes the server-side `modified_since` filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never modified_at, which would
    # rewrite partitions on every sync.
    partition_key: Optional[str] = None


# OnePageCRM API v3 list endpoints (https://developer.onepagecrm.com/api/). Contacts, deals,
# actions, notes, calls, and meetings support incremental sync via the server-side
# `modified_since` UNIX-timestamp filter; companies documents no `modified_since`, and the config
# endpoints (users, statuses, lead_sources) are small unpaginated lists — all full refresh only.
ONEPAGECRM_ENDPOINTS: dict[str, OnepagecrmEndpointConfig] = {
    "contacts": OnepagecrmEndpointConfig(
        name="contacts",
        path="/contacts",
        data_key="contacts",
        item_key="contact",
        supports_sort=True,
        incremental_fields=[MODIFIED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    "companies": OnepagecrmEndpointConfig(
        name="companies",
        path="/companies",
        data_key="companies",
        item_key="company",
        supports_sort=True,
        partition_key="created_at",
    ),
    "deals": OnepagecrmEndpointConfig(
        name="deals",
        path="/deals",
        data_key="deals",
        item_key="deal",
        supports_sort=True,
        incremental_fields=[MODIFIED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    "actions": OnepagecrmEndpointConfig(
        name="actions",
        path="/actions",
        data_key="actions",
        item_key="action",
        supports_sort=True,
        incremental_fields=[MODIFIED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    "notes": OnepagecrmEndpointConfig(
        name="notes",
        path="/notes",
        data_key="notes",
        item_key="note",
        supports_sort=True,
        incremental_fields=[MODIFIED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    "calls": OnepagecrmEndpointConfig(
        name="calls",
        path="/calls",
        data_key="calls",
        item_key="call",
        supports_sort=True,
        incremental_fields=[MODIFIED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    "meetings": OnepagecrmEndpointConfig(
        name="meetings",
        path="/meetings",
        data_key="meetings",
        item_key="meeting",
        supports_sort=True,
        incremental_fields=[MODIFIED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    "users": OnepagecrmEndpointConfig(
        name="users",
        path="/users",
        data_key=None,
        item_key="user",
        paginated=False,
    ),
    "statuses": OnepagecrmEndpointConfig(
        name="statuses",
        path="/statuses",
        data_key=None,
        item_key="status",
        paginated=False,
    ),
    "lead_sources": OnepagecrmEndpointConfig(
        name="lead_sources",
        path="/lead_sources",
        data_key=None,
        item_key=None,
        paginated=False,
    ),
}

ENDPOINTS = tuple(ONEPAGECRM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ONEPAGECRM_ENDPOINTS.items() if config.incremental_fields
}
