from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Bloomerang's v2 list endpoints cap `take` at 50 (confirmed via the Parsons client library, which
# clamps page_size to this maximum).
PAGE_SIZE = 50


def _last_modified_incremental_fields() -> list[IncrementalField]:
    # Only endpoints whose rows carry AuditTrail.LastModifiedDate *and* whose list action accepts a
    # server-side `lastModified` filter get this. See BloomerangEndpointConfig.supports_incremental.
    return [
        {
            "label": "LastModifiedDate",
            "type": IncrementalFieldType.DateTime,
            "field": "LastModifiedDate",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class BloomerangEndpointConfig:
    name: str
    path: str  # path under https://api.bloomerang.co/v2
    # Whether the list action accepts a server-side `lastModified` filter (Constituents only —
    # Transactions/Interactions accept `orderBy=LastModifiedDate` for sorting but no filter param).
    supports_incremental: bool
    # Whether the list action accepts `orderBy`/`orderDirection` at all (Appeals/Campaigns/Funds
    # accept neither, per the API's own parameter docs).
    supports_sort: bool
    # Whether rows carry a nested `AuditTrail` object ({CreatedDate, LastModifiedDate, ...}) that
    # gets flattened onto the row root. Appeals/Campaigns/Funds have no AuditTrail field.
    has_audit_trail: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["Id"])
    # Stable creation-time column to partition by. None when the endpoint has no AuditTrail.
    partition_key: Optional[str] = "CreatedDate"


BLOOMERANG_ENDPOINTS: dict[str, BloomerangEndpointConfig] = {
    "Constituents": BloomerangEndpointConfig(
        name="Constituents",
        path="constituents",
        supports_incremental=True,
        supports_sort=True,
        has_audit_trail=True,
        incremental_fields=_last_modified_incremental_fields(),
    ),
    "Transactions": BloomerangEndpointConfig(
        name="Transactions",
        path="transactions",
        supports_incremental=False,
        supports_sort=True,
        has_audit_trail=True,
    ),
    "Interactions": BloomerangEndpointConfig(
        name="Interactions",
        path="interactions",
        supports_incremental=False,
        supports_sort=True,
        has_audit_trail=True,
    ),
    "Appeals": BloomerangEndpointConfig(
        name="Appeals",
        path="appeals",
        supports_incremental=False,
        supports_sort=False,
        has_audit_trail=False,
        partition_key=None,
    ),
    "Campaigns": BloomerangEndpointConfig(
        name="Campaigns",
        path="campaigns",
        supports_incremental=False,
        supports_sort=False,
        has_audit_trail=False,
        partition_key=None,
    ),
    "Funds": BloomerangEndpointConfig(
        name="Funds",
        path="funds",
        supports_incremental=False,
        supports_sort=False,
        has_audit_trail=False,
        partition_key=None,
    ),
}

ENDPOINTS = tuple(BLOOMERANG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BLOOMERANG_ENDPOINTS.items()
}
