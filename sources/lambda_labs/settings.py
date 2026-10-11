from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class LambdaLabsEndpoint:
    name: str
    path: str
    primary_keys: list[str]
    # Dotted path to the record list within the JSON body. Lambda wraps every payload in a
    # top-level `data` key; `tickets` nests its list one level deeper under `data.tickets`.
    records_path: str = "data"
    # Dotted path to the next-page cursor, or None when the endpoint returns the whole list in a
    # single response (most Lambda list endpoints are unpaginated).
    page_token_path: Optional[str] = None
    # `data` is an object keyed by id rather than a list (only `/instance-types`).
    is_map: bool = False
    # Stable creation-style timestamp to partition by; never an `updated_at`-style field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the API exposes a genuine server-side timestamp filter (audit-events `start`).
    supports_incremental: bool = False


# Only `audit-events` accepts server-side `start`/`end` timestamp filters, so it is the only
# endpoint synced incrementally. Every other list endpoint returns the full collection with no
# time filter, so those are full-refresh only (declaring them incremental would re-fetch the whole
# list each run at no saving).
LAMBDA_LABS_ENDPOINTS: dict[str, LambdaLabsEndpoint] = {
    "instances": LambdaLabsEndpoint(name="instances", path="/instances", primary_keys=["id"]),
    "instance_types": LambdaLabsEndpoint(
        name="instance_types", path="/instance-types", primary_keys=["name"], is_map=True
    ),
    "filesystems": LambdaLabsEndpoint(name="filesystems", path="/file-systems", primary_keys=["id"]),
    "images": LambdaLabsEndpoint(name="images", path="/images", primary_keys=["id"]),
    "ssh_keys": LambdaLabsEndpoint(name="ssh_keys", path="/ssh-keys", primary_keys=["id"]),
    "firewall_rulesets": LambdaLabsEndpoint(name="firewall_rulesets", path="/firewall-rulesets", primary_keys=["id"]),
    "regions": LambdaLabsEndpoint(name="regions", path="/regions", primary_keys=["name"]),
    "audit_events": LambdaLabsEndpoint(
        name="audit_events",
        path="/audit-events",
        primary_keys=["event_id"],
        page_token_path="page_token",
        partition_key="event_time",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "event_time",
                "type": IncrementalFieldType.DateTime,
                "field": "event_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "tickets": LambdaLabsEndpoint(
        name="tickets",
        path="/tickets",
        primary_keys=["id"],
        records_path="data.tickets",
        page_token_path="data.page_token",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(LAMBDA_LABS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LAMBDA_LABS_ENDPOINTS.items()
}
