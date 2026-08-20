from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class OutreachEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # createdAt is set once and never changes, unlike updatedAt, so it makes a stable partition key.
    partition_key: str = "createdAt"


OUTREACH_ENDPOINTS: dict[str, OutreachEndpointConfig] = {
    "prospects": OutreachEndpointConfig(name="prospects", path="/prospects"),
    "accounts": OutreachEndpointConfig(name="accounts", path="/accounts"),
    "sequences": OutreachEndpointConfig(name="sequences", path="/sequences"),
    "sequenceStates": OutreachEndpointConfig(name="sequenceStates", path="/sequenceStates"),
    "mailings": OutreachEndpointConfig(name="mailings", path="/mailings"),
    "calls": OutreachEndpointConfig(name="calls", path="/calls"),
    "users": OutreachEndpointConfig(name="users", path="/users"),
    "stages": OutreachEndpointConfig(name="stages", path="/stages"),
}

ENDPOINTS = tuple(OUTREACH_ENDPOINTS.keys())

# Every endpoint's `attributes` object carries both createdAt and updatedAt (confirmed against
# Outreach's published OpenAPI schema), so all eight support the same updatedAt cursor filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [incremental_field("updatedAt")] for name in ENDPOINTS}
