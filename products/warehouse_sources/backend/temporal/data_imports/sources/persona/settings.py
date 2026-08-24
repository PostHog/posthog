from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Persona's list endpoints return records newest-first (reverse-chronological on created-at) and are
# paginated with a `page[after]=<object id>` cursor. Incremental endpoints expose a server-side
# `filter[created-at-start]` window on the immutable `created-at` timestamp; there is no `updated-at`
# filter, so every advertised incremental cursor is a `created-at` timestamp. Object ids are globally
# unique and type-prefixed (e.g. `inq_...`, `acc_...`), so `id` is a safe standalone primary key.


def _created_at_incremental_fields(column: str = "created_at") -> list[IncrementalField]:
    # Persona attribute `created-at` normalizes to the `created_at` warehouse column (the pipeline
    # snake-cases identifiers), so both the advertised incremental field and the partition key use it.
    return [
        {
            "label": column,
            "type": IncrementalFieldType.DateTime,
            "field": column,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass(frozen=True, kw_only=True)
class PersonaFanout:
    """How to reach a resource Persona only exposes underneath a parent object.

    Persona has no cross-parent list endpoint for these, and it rejects `include` on list endpoints,
    so each parent from the list walk is re-fetched individually with `?include=<relationship>` and
    the hydrated children are read out of the response's `included` array.
    """

    relationship: str
    # Persona sub-types its child objects (`verification/government-id`, `verification/selfie`, …).
    # Matching on the prefix keeps the rows to one resource even if a response carries more.
    type_prefix: str
    # Parent identifiers copied onto every child row, as `{parent_key_prefix}-id` /
    # `{parent_key_prefix}-created-at`.
    parent_key_prefix: str


@dataclass
class PersonaEndpointConfig:
    name: str
    # For a fan-out endpoint this is the parent's list path, not the child's.
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # A stable created-at column to partition on. Kept in the normalized (snake_case) form the
    # pipeline sees after column-name normalization. `None` disables partitioning.
    partition_key: Optional[str] = "created_at"
    # True only when the list endpoint exposes the server-side `filter[created-at-start]` window.
    supports_incremental: bool = True
    # Append-only immutable log (e.g. events) — synced with append semantics, never merged.
    append_only: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Set when the rows come from hydrating each parent rather than from the list response itself.
    fanout: Optional[PersonaFanout] = None


PERSONA_ENDPOINTS: dict[str, PersonaEndpointConfig] = {
    "inquiries": PersonaEndpointConfig(
        name="inquiries",
        path="/inquiries",
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Verification detail is only reachable one inquiry at a time, so this table costs one extra
    # request per inquiry in the window. It's off by default for that reason — a user who wants
    # attempt-level data opts in, and everyone else keeps the cheap inquiry-level sync.
    "verifications": PersonaEndpointConfig(
        name="verifications",
        path="/inquiries",
        fanout=PersonaFanout(relationship="verifications", type_prefix="verification/", parent_key_prefix="inquiry"),
        # A verification's own `created-at` can't drive the window: the window is applied to the
        # inquiry list we walk, and an inquiry created before the watermark can still gain a
        # verification after it. Advertising the parent's timestamp keeps the cursor and the filter
        # on the same field. Retries on an already-synced inquiry are picked up on a full refresh.
        incremental_fields=_created_at_incremental_fields("inquiry_created_at"),
        partition_key="inquiry_created_at",
        should_sync_default=False,
    ),
    "accounts": PersonaEndpointConfig(
        name="accounts",
        path="/accounts",
        incremental_fields=_created_at_incremental_fields(),
    ),
    "cases": PersonaEndpointConfig(
        name="cases",
        path="/cases",
        incremental_fields=_created_at_incremental_fields(),
    ),
    "transactions": PersonaEndpointConfig(
        name="transactions",
        path="/transactions",
        incremental_fields=_created_at_incremental_fields(),
    ),
    "events": PersonaEndpointConfig(
        name="events",
        path="/events",
        incremental_fields=_created_at_incremental_fields(),
        append_only=True,
    ),
    # Inquiry templates are configuration objects (small, low churn). We don't rely on a created-at
    # window here — full refresh keeps the catalog complete and simple.
    "inquiry_templates": PersonaEndpointConfig(
        name="inquiry_templates",
        path="/inquiry-templates",
        supports_incremental=False,
        partition_key=None,
    ),
}

ENDPOINTS = tuple(PERSONA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PERSONA_ENDPOINTS.items()
}
