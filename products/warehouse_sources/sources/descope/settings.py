from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Users",
    "Audit",
    "Tenants",
    "Roles",
    "AccessKeys",
    "Permissions",
    "Groups",
    "UserHistory",
    "Analytics",
)

# Users and Audit support real server-side timestamp filters (verified against the official
# descope/python-sdk and descope/node-sdk management clients). Every other endpoint is an
# unpaginated full list with no timestamp filter, so they're full-refresh only (omitted here).
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
    "Permissions": ["id"],
    # Group ids come from the customer's identity provider, so they are only unique within the
    # tenant the group was loaded for.
    "Groups": ["tenantId", "id"],
    # Neither authentication history nor the analytics aggregate carries a record id, so both get
    # a synthetic one derived from the fields that make the row unique — see descope.py.
    "UserHistory": ["id"],
    "Analytics": ["id"],
}

# A stable field to partition on — never the incremental cursor a user could pick (e.g. modifiedTime),
# since that changes over time and would rewrite partitions on every sync. Endpoints absent here
# carry no timestamp at all: permissions, groups and the analytics aggregate sync unpartitioned.
PARTITION_KEYS: dict[str, str] = {
    "Users": "createdTime",
    "Audit": "occurred",
    "Tenants": "createdTime",
    "Roles": "createdTime",
    "AccessKeys": "createdTime",
    "UserHistory": "loginTime",
}

# `POST /v1/mgmt/analytics/search` rejects a `from` further back than 12 months. Ask for a day
# less: the window is computed when the resource is built and the request goes out later, so
# asking for the full 365 days would put a retry outside the limit. Every sync pulls the whole
# window, since the response carries no cursor a later sync could resume from.
ANALYTICS_LOOKBACK_DAYS = 364
# How the aggregate buckets its dates: "h" hour, "d" day, "w" week, "m" month, "q" quarter.
ANALYTICS_BUCKET = "d"
