from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Users",
    "Audit",
    "Tenants",
    "Roles",
    "AccessKeys",
)

# Users and Audit support real server-side timestamp filters (verified against the official
# descope/python-sdk and descope/node-sdk management clients). Tenants/Roles/AccessKeys are small,
# unpaginated full lists with no timestamp filter, so they're full-refresh only (omitted here).
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Users": [
        {
            "label": "createdTime",
            "type": IncrementalFieldType.DateTime,
            "field": "createdTime",
            "field_type": IncrementalFieldType.Integer,
        },
        {
            "label": "modifiedTime",
            "type": IncrementalFieldType.DateTime,
            "field": "modifiedTime",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Audit": [
        {
            "label": "occurred",
            "type": IncrementalFieldType.DateTime,
            "field": "occurred",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}

# `POST /v2/mgmt/user/search` field name for each advertised incremental cursor.
USER_INCREMENTAL_TIME_PARAMS: dict[str, str] = {
    "createdTime": "fromCreatedTime",
    "modifiedTime": "fromModifiedTime",
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "Users": ["userId"],
    # Descope's audit search has no unique record id (verified: absent from both official SDKs'
    # response types) — a synthetic one is derived from the event's identity fields, see descope.py.
    "Audit": ["id"],
    "Tenants": ["id"],
    "Roles": ["id"],
    "AccessKeys": ["id"],
}

# A stable field to partition on — never the incremental cursor a user could pick (e.g. modifiedTime),
# since that changes over time and would rewrite partitions on every sync.
PARTITION_KEYS: dict[str, str] = {
    "Users": "createdTime",
    "Audit": "occurred",
    "Tenants": "createdTime",
    "Roles": "createdTime",
    "AccessKeys": "createdTime",
}
