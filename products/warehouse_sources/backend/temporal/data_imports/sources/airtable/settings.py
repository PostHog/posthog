from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AirtableEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Records can be filtered server-side with filterByFormula on CREATED_TIME(),
# giving an honest append-only incremental on createdTime (the only timestamp
# present on record payloads — updates to existing records need a full
# refresh). Bases and tables are tiny metadata listings.
AIRTABLE_ENDPOINTS: dict[str, AirtableEndpointConfig] = {
    "bases": AirtableEndpointConfig(
        name="bases",
    ),
    "tables": AirtableEndpointConfig(
        name="tables",
        # Table ids are globally unique, but keep the base linkage in the key
        # so re-parented metadata can't collide.
        primary_keys=["_base_id", "id"],
    ),
    "records": AirtableEndpointConfig(
        name="records",
        # Record ids are only unique within a table.
        primary_keys=["_base_id", "_table_id", "id"],
        incremental_fields=[
            {
                "label": "createdTime",
                "type": IncrementalFieldType.DateTime,
                "field": "createdTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(AIRTABLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AIRTABLE_ENDPOINTS.items() if config.incremental_fields
}
