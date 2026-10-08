from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


CREATED = "created_datetime"
UPDATED = "updated_datetime"


@dataclass(frozen=True)
class GorgiasEndpointConfig:
    name: str
    path: str
    # Stable creation-time field used for datetime partitioning. Gorgias exposes
    # `created_datetime` on every list resource and it never changes once set —
    # never partition on `updated_datetime`, which rewrites partitions on each sync.
    partition_key: str = CREATED
    # Explicit ascending sort on the stable creation field keeps page boundaries
    # stable across a full-refresh sync even if rows are inserted while we paginate.
    # Most list endpoints accept `created_datetime:asc` (verified against the docs).
    # None for endpoints that accept no `order_by` at all (voice calls).
    order_by: str | None = f"{CREATED}:asc"
    # Datetime attributes this endpoint actually accepts in `order_by` — verified
    # per-endpoint against the Gorgias docs, because they differ: `users` exposes no
    # `updated_datetime` (only name/email/role), `messages` is created-only, etc.
    # Drives both the advertised incremental fields and a runtime guard that refuses to
    # send a sort the API would reject (a rejected/ignored sort silently corrupts the
    # newest-first ordering that incremental relies on).
    sortable_datetime_fields: frozenset[str] = frozenset({CREATED})
    # Datetime fields the endpoint filters server-side with `<field>[gte]`. Incremental on one
    # of these sorts ascending and requests only rows from the watermark onwards, rather than
    # walking newest-first and stopping client-side.
    filterable_datetime_fields: frozenset[str] = frozenset()
    # Whether this endpoint can sync incrementally. Gorgias has no server-side time
    # filter, so incremental relies on sorting the cursor `<field>:desc` and halting
    # once a whole page predates the watermark. Only safe when the cursor field both
    # reflects the change we care about AND is server-sortable: `updated_datetime` for
    # mutable resources, `created_datetime` for append-only ones. Mutable resources that
    # expose only `created_datetime` (users/tags/views/teams) stay full-refresh, since
    # `created_datetime` incremental would silently miss edits to existing rows.
    supports_incremental: bool = False
    # Cursor fields offered to the user. Only advertise a field whose desc-sort yields
    # correct incremental semantics for this resource (must be in sortable_datetime_fields).
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: tuple[str, ...] = ("id",)
    # One full pagination pass per entry, merged into a single table. `custom-fields`
    # requires `object_type`, so it is listed once per type.
    param_variants: tuple[dict[str, str], ...] = ({},)
    # Name of a nested collection on each ticket to flatten into one row per item. The
    # ticket list already embeds `tags` and `custom_fields`, so this avoids one request per
    # ticket against the per-ticket `/tickets/{id}/tags` and `/tickets/{id}/custom-fields`.
    ticket_child: str | None = None
    # Per-row child path (`{id}` is the row id of `path`), fetched for every row and flattened
    # into one row per child item. Costs one request per parent row, so only for collections
    # the parent list does not embed.
    child_path: str | None = None


GORGIAS_ENDPOINTS: dict[str, GorgiasEndpointConfig] = {
    "tickets": GorgiasEndpointConfig(
        name="tickets",
        path="/tickets",
        sortable_datetime_fields=frozenset({CREATED, UPDATED}),
        supports_incremental=True,
        incremental_fields=[_datetime_field(UPDATED)],
    ),
    "messages": GorgiasEndpointConfig(
        name="messages",
        path="/messages",
        sortable_datetime_fields=frozenset({CREATED}),
        supports_incremental=True,
        incremental_fields=[_datetime_field(CREATED)],
    ),
    "customers": GorgiasEndpointConfig(
        name="customers",
        path="/customers",
        sortable_datetime_fields=frozenset({CREATED, UPDATED}),
        supports_incremental=True,
        incremental_fields=[_datetime_field(UPDATED)],
    ),
    # `users` is mutable but Gorgias does not expose `updated_datetime` in its order_by
    # (only created_datetime/name/email/role), so there is no correct incremental cursor —
    # full refresh only. The table is small, so this is cheap.
    "users": GorgiasEndpointConfig(
        name="users",
        path="/users",
        sortable_datetime_fields=frozenset({CREATED}),
    ),
    "satisfaction_surveys": GorgiasEndpointConfig(
        name="satisfaction_surveys",
        path="/satisfaction-surveys",
        sortable_datetime_fields=frozenset({CREATED}),
        supports_incremental=True,
        incremental_fields=[_datetime_field(CREATED)],
    ),
    "macros": GorgiasEndpointConfig(
        name="macros",
        path="/macros",
        sortable_datetime_fields=frozenset({CREATED, UPDATED}),
        supports_incremental=True,
        incremental_fields=[_datetime_field(UPDATED)],
    ),
    # tags/views/teams are mutable config but expose only `created_datetime` for sorting,
    # so incremental would miss edits — full refresh only.
    "tags": GorgiasEndpointConfig(
        name="tags",
        path="/tags",
        sortable_datetime_fields=frozenset({CREATED}),
    ),
    "views": GorgiasEndpointConfig(
        name="views",
        path="/views",
        sortable_datetime_fields=frozenset({CREATED}),
    ),
    "teams": GorgiasEndpointConfig(
        name="teams",
        path="/teams",
        sortable_datetime_fields=frozenset({CREATED}),
    ),
    "custom_fields": GorgiasEndpointConfig(
        name="custom_fields",
        path="/custom-fields",
        order_by="priority:asc",
        sortable_datetime_fields=frozenset(),
        param_variants=({"object_type": "Ticket"}, {"object_type": "Customer"}),
    ),
    "voice_calls": GorgiasEndpointConfig(
        name="voice_calls",
        path="/phone/voice-calls",
        order_by=None,
        sortable_datetime_fields=frozenset(),
    ),
    "voice_call_events": GorgiasEndpointConfig(
        name="voice_call_events",
        path="/phone/voice-call-events",
        order_by=None,
        sortable_datetime_fields=frozenset(),
    ),
    "voice_call_recordings": GorgiasEndpointConfig(
        name="voice_call_recordings",
        path="/phone/voice-call-recordings",
        order_by=None,
        sortable_datetime_fields=frozenset(),
    ),
    # Append-only audit log. Gorgias keeps only the last 12 months of events.
    "events": GorgiasEndpointConfig(
        name="events",
        path="/events",
        sortable_datetime_fields=frozenset({CREATED}),
        filterable_datetime_fields=frozenset({CREATED}),
        supports_incremental=True,
        incremental_fields=[_datetime_field(CREATED)],
    ),
    # Derived from the ticket list, so they stay full refresh: a removed tag or cleared field
    # value has no ticket-level row left to delete it on merge.
    "ticket_tags": GorgiasEndpointConfig(
        name="ticket_tags",
        path="/tickets",
        partition_key=f"ticket_{CREATED}",
        sortable_datetime_fields=frozenset({CREATED, UPDATED}),
        primary_keys=("ticket_id", "id"),
        ticket_child="tags",
    ),
    "ticket_field_values": GorgiasEndpointConfig(
        name="ticket_field_values",
        path="/tickets",
        partition_key=f"ticket_{CREATED}",
        sortable_datetime_fields=frozenset({CREATED, UPDATED}),
        primary_keys=("ticket_id", "field_id"),
        ticket_child="custom_fields",
    ),
    # The customer list does not embed custom field values, so this fans out one request per
    # customer. Full refresh for the same reason as the ticket-derived tables.
    "customer_field_values": GorgiasEndpointConfig(
        name="customer_field_values",
        path="/customers",
        partition_key=f"customer_{CREATED}",
        sortable_datetime_fields=frozenset({CREATED, UPDATED}),
        primary_keys=("customer_id", "field_id"),
        child_path="/customers/{id}/custom-fields",
    ),
}

ENDPOINTS = tuple(GORGIAS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GORGIAS_ENDPOINTS.items()
}
