from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every Lob list object carries a stable, immutable `date_created` timestamp. We use it both as the
# partition key (it never changes once a resource is created) and, where the endpoint can be sorted
# ascending, as the incremental cursor via the server-side `date_created[gt]` filter.
DATE_CREATED_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date_created",
    "type": IncrementalFieldType.DateTime,
    "field": "date_created",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class LobEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Whether to advertise incremental sync for this endpoint. Only set when the endpoint accepts
    # `sort_by[date_created]=asc` so we can paginate forward over a server-side `date_created[gt]`
    # filter; a forward-only ascending cursor stays above the watermark on every page and terminates
    # naturally. Endpoints that only sort newest-first stay full refresh to avoid an unbounded
    # walk-back through history when the cursor drops the time filter.
    supports_incremental: bool = False
    # Field to partition by. Always a creation-time field so partitions never rewrite.
    partition_key: Optional[str] = "date_created"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


LOB_ENDPOINTS: dict[str, LobEndpointConfig] = {
    # Mailpieces: support `sort_by[date_created]` so we can force ascending order for incremental sync.
    "letters": LobEndpointConfig(
        name="letters",
        path="/letters",
        supports_incremental=True,
        incremental_fields=[DATE_CREATED_INCREMENTAL_FIELD],
    ),
    "postcards": LobEndpointConfig(
        name="postcards",
        path="/postcards",
        supports_incremental=True,
        incremental_fields=[DATE_CREATED_INCREMENTAL_FIELD],
    ),
    "checks": LobEndpointConfig(
        name="checks",
        path="/checks",
        supports_incremental=True,
        incremental_fields=[DATE_CREATED_INCREMENTAL_FIELD],
    ),
    "self_mailers": LobEndpointConfig(
        name="self_mailers",
        path="/self_mailers",
        supports_incremental=True,
        incremental_fields=[DATE_CREATED_INCREMENTAL_FIELD],
    ),
    # Addresses, bank accounts and templates expose `date_created` filtering but no `sort_by`, so they
    # only return newest-first. A descending cursor can walk past the watermark into full history if
    # the server drops the time filter on later pages, so these stay full refresh until that can be
    # verified against the live API.
    "addresses": LobEndpointConfig(name="addresses", path="/addresses"),
    "bank_accounts": LobEndpointConfig(name="bank_accounts", path="/bank_accounts"),
    "templates": LobEndpointConfig(name="templates", path="/templates"),
    # Campaigns expose no `date_created` filter at all, so full refresh is the only option.
    "campaigns": LobEndpointConfig(name="campaigns", path="/campaigns"),
}

ENDPOINTS = tuple(LOB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LOB_ENDPOINTS.items()
}
