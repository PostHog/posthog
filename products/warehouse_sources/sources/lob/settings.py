from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# Every Lob list object carries a stable, immutable `date_created` timestamp. We use it both as the
# partition key (it never changes once a resource is created) and, where the endpoint can be sorted
# ascending, as the incremental cursor via the server-side `date_created[gt]` filter.
DATE_CREATED_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date_created",
    "type": IncrementalFieldType.DateTime,
    "field": "date_created",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass(frozen=True)
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
    # Most Lob lists page with a `next_url` cursor; a few only accept `offset`, and `/uploads` returns
    # every row in a single bare array.
    pagination: Literal["cursor", "offset", "none"] = "cursor"
    # Fan-out child endpoints: `path` holds a `{parent_id}` placeholder that is filled from each row of
    # the `parent` endpoint, and `parent_id_field` stamps that id onto every child row.
    parent: Optional[str] = None
    parent_id_field: Optional[str] = None


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
    "snap_packs": LobEndpointConfig(
        name="snap_packs",
        path="/snap_packs",
        supports_incremental=True,
        incremental_fields=[DATE_CREATED_INCREMENTAL_FIELD],
    ),
    "booklets": LobEndpointConfig(
        name="booklets",
        path="/booklets",
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
    "billing_groups": LobEndpointConfig(
        name="billing_groups",
        path="/billing_groups",
        supports_incremental=True,
        incremental_fields=[DATE_CREATED_INCREMENTAL_FIELD],
        pagination="offset",
    ),
    # One row per QR-coded mailpiece, ordered by most recent scan. Scans keep landing on old rows and
    # there is no sort or scan-date filter, so full refresh is the only way to pick them up.
    "qr_code_analytics": LobEndpointConfig(
        name="qr_code_analytics",
        path="/qr_code_analytics",
        primary_keys=["resource_id"],
        pagination="offset",
    ),
    # Cards only accept the `before`/`after` cursor, with no sort or date filter.
    "cards": LobEndpointConfig(name="cards", path="/cards"),
    "card_orders": LobEndpointConfig(
        name="card_orders",
        path="/cards/{parent_id}/orders",
        primary_keys=["card_id", "id"],
        pagination="offset",
        parent="cards",
        parent_id_field="card_id",
    ),
    # Version rows carry no template id, so the parent id is stamped on as `template_id`.
    "template_versions": LobEndpointConfig(
        name="template_versions",
        path="/templates/{parent_id}/versions",
        primary_keys=["template_id", "id"],
        parent="templates",
        parent_id_field="template_id",
    ),
    # Uploads use camelCase fields, unlike the rest of the Lob API.
    "uploads": LobEndpointConfig(name="uploads", path="/uploads", partition_key="dateCreated", pagination="none"),
}

ENDPOINTS = tuple(LOB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LOB_ENDPOINTS.items()
}
