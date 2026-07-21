from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class SavvyCalEndpointConfig:
    name: str
    path: str
    # SavvyCal object IDs are prefixed ULIDs (event_..., link_..., wbhk_..., wkflw_...), unique
    # across the account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Extra query params sent on every request to this endpoint.
    params: dict[str, str] = field(default_factory=dict)
    # Stable datetime column to partition on (never a mutable field like start_at).
    partition_key: str | None = None
    # Fields stripped from every row before it lands in the warehouse. Used to keep upstream
    # secrets (e.g. webhook signing secrets) out of a table any project member can query.
    redact_fields: frozenset[str] = field(default_factory=frozenset)


# SavvyCal v1 REST list endpoints (https://api.savvycal.com/v1/spec). Only `events` supports
# incremental sync: the API exposes `from`/`until` bounds on the event *start date* (with
# `period=fixed`) plus a `direction` sort, but no resource has an updated-after / last-modified
# cursor, so every other stream is full refresh only.
SAVVYCAL_ENDPOINTS: dict[str, SavvyCalEndpointConfig] = {
    "events": SavvyCalEndpointConfig(
        name="events",
        path="/events",
        # Defaults are period=upcoming, state=confirmed, attendance=attending — far narrower than
        # what a warehouse import wants, so widen every filter. `period` is set per-sync in the
        # transport ("all" for full refresh, "fixed" + `from` for incremental).
        params={"state": "all", "attendance": "any", "direction": "asc"},
        partition_key="created_at",
    ),
    "links": SavvyCalEndpointConfig(name="links", path="/links"),
    # The webhook object carries a `secret` (its signing secret); redact it so it never reaches the
    # warehouse table.
    "webhooks": SavvyCalEndpointConfig(
        name="webhooks", path="/webhooks", partition_key="created_at", redact_fields=frozenset({"secret"})
    ),
    "workflows": SavvyCalEndpointConfig(name="workflows", path="/workflows", partition_key="created_at"),
}

ENDPOINTS = tuple(SAVVYCAL_ENDPOINTS.keys())

# `from` filters events on their start date server-side, so start_at is the only genuine
# incremental cursor. Caveat (documented in the source docs): updates to events that started
# before the watermark — e.g. a cancellation of a past event — are only picked up by a full
# refresh; a reschedule moves start_at forward and is re-fetched naturally.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "events": [
        {
            "label": "start_at",
            "type": IncrementalFieldType.DateTime,
            "field": "start_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
