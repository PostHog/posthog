from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Persona's list endpoints return records newest-first (reverse-chronological on created-at) and are
# paginated with a `page[after]=<object id>` cursor. Incremental endpoints expose a server-side
# `filter[created-at-start]` window on the immutable `created-at` timestamp; there is no `updated-at`
# filter, so the only advertised incremental cursor is `created_at`. Object ids are globally unique
# and type-prefixed (e.g. `inq_...`, `acc_...`), so `id` is a safe standalone primary key.


def _created_at_incremental_fields() -> list[IncrementalField]:
    # Persona attribute `created-at` normalizes to the `created_at` warehouse column (the pipeline
    # snake-cases identifiers), so both the advertised incremental field and the partition key use it.
    return [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class PersonaEndpointConfig:
    name: str
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


PERSONA_ENDPOINTS: dict[str, PersonaEndpointConfig] = {
    "inquiries": PersonaEndpointConfig(
        name="inquiries",
        path="/inquiries",
        incremental_fields=_created_at_incremental_fields(),
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
