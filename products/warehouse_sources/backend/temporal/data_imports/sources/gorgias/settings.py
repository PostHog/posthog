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


@dataclass
class GorgiasEndpointConfig:
    name: str
    path: str
    # Stable creation-time field used for datetime partitioning. Gorgias exposes
    # `created_datetime` on every list resource and it never changes once set —
    # never partition on `updated_datetime`, which rewrites partitions on each sync.
    partition_key: str = CREATED
    # Explicit ascending sort on the stable creation field keeps page boundaries
    # stable across a full-refresh sync even if rows are inserted while we paginate.
    # Every list endpoint accepts `created_datetime:asc` (verified against the docs).
    order_by: str = f"{CREATED}:asc"
    # Datetime attributes this endpoint actually accepts in `order_by` — verified
    # per-endpoint against the Gorgias docs, because they differ: `users` exposes no
    # `updated_datetime` (only name/email/role), `messages` is created-only, etc.
    # Drives both the advertised incremental fields and a runtime guard that refuses to
    # send a sort the API would reject (a rejected/ignored sort silently corrupts the
    # newest-first ordering that incremental relies on).
    sortable_datetime_fields: frozenset[str] = frozenset({CREATED})
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
}

ENDPOINTS = tuple(GORGIAS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GORGIAS_ENDPOINTS.items()
}
