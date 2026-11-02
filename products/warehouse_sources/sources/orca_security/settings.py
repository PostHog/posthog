from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Region -> Serving Layer API base URL. Orca hosts a US and an EU cloud plus a generic
# default; the token is only valid for the region it was generated in, so the user picks one.
ORCA_REGION_HOSTS: dict[str, str] = {
    "global": "https://api.orcasecurity.io/api",
    "us": "https://app.us.orcasecurity.io/api",
    "eu": "https://app.eu.orcasecurity.io/api",
}
DEFAULT_REGION = "global"

# Everything funnels through the single Serving Layer query endpoint; each stream just
# swaps the Orca model it asks for in the POST body.
QUERY_PATH = "/serving-layer/query"

PAGE_SIZE = 1000


@dataclass
class OrcaEndpointConfig:
    name: str
    # Orca Serving Layer model queried in the object_set body (e.g. "Alert", "Inventory").
    model: str
    incremental_fields: list[IncrementalField]
    # Serving Layer field the server-side `date_gte` filter is applied to, e.g. "CreatedAt".
    # None => no verified server-side timestamp filter, so this stream is full-refresh only.
    incremental_key: Optional[str] = None
    # Stable field to partition by. Must never change after creation (created-style, not last-seen).
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


ORCA_ENDPOINTS: dict[str, OrcaEndpointConfig] = {
    # Security alerts (misconfigurations, malicious activity, etc). CreatedAt is stable and the
    # Serving Layer honors a `date_gte` filter on it, so this is the one incremental stream.
    "alerts": OrcaEndpointConfig(
        name="alerts",
        model="Alert",
        incremental_key="CreatedAt",
        partition_key="CreatedAt",
        incremental_fields=[
            {
                "label": "CreatedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "CreatedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Cloud asset inventory (EC2 instances, buckets, functions, ...). The Serving Layer exposes
    # this as the `Inventory` model. No verified server-side timestamp filter, so full refresh.
    "assets": OrcaEndpointConfig(
        name="assets",
        model="Inventory",
        incremental_fields=[],
    ),
    # Connected cloud accounts/subscriptions/projects.
    "cloud_accounts": OrcaEndpointConfig(
        name="cloud_accounts",
        model="CloudAccount",
        incremental_fields=[],
    ),
    # Detected CVEs / vulnerabilities across scanned assets.
    "vulnerabilities": OrcaEndpointConfig(
        name="vulnerabilities",
        model="CVE",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(ORCA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ORCA_ENDPOINTS.items()
}
