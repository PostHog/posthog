from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Rows don't carry an export timestamp themselves, so the transport injects the
# producing job's updatedAt — that injected field is the incremental cursor.
_JOB_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "_job_updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "_job_updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class GladlyEndpointConfig:
    name: str
    # Filename inside each export job (e.g. customers.jsonl).
    filename: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_JOB_INCREMENTAL_FIELDS))


# Gladly has no list-all REST surface — bulk data ships as JSONL files inside
# vendor-scheduled export jobs (hourly/daily, 14-day retention). Every stream
# maps to one file per job; jobs are processed oldest-first so the watermark
# advances monotonically, and merge-on-id dedupes records that appear in
# multiple exports.
GLADLY_ENDPOINTS: dict[str, GladlyEndpointConfig] = {
    "customers": GladlyEndpointConfig(
        name="customers",
        filename="customers.jsonl",
    ),
    "conversation_items": GladlyEndpointConfig(
        name="conversation_items",
        filename="conversation_items.jsonl",
    ),
    "agents": GladlyEndpointConfig(
        name="agents",
        filename="agents.jsonl",
    ),
    "topics": GladlyEndpointConfig(
        name="topics",
        filename="topics.jsonl",
    ),
}

ENDPOINTS = tuple(GLADLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GLADLY_ENDPOINTS.items() if config.incremental_fields
}
