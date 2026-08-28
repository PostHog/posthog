from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Documents",
    "Folders",
    "Connections",
    "Schedules",
    "Users",
    "UserGroups",
)

# Only Documents exposes anything close to a timestamp cursor (`sortField=updatedAt`, no
# server-side `updatedAt`-since filter). Folders/Schedules only sort by name/path/favorites;
# Connections and the SCIM Users/UserGroups endpoints return their full result unpaginated or
# sorted purely by creation order, with no timestamp filter at all — full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Documents": [
        {
            "label": "updatedAt",
            "type": IncrementalFieldType.DateTime,
            "field": "updatedAt",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

# Documents has no `id` field in the API response — only `identifier`, which is unique
# per-organization and used in the document's URL.
PRIMARY_KEYS: dict[str, list[str]] = {
    "Documents": ["identifier"],
    "Folders": ["id"],
    "Connections": ["id"],
    "Schedules": ["id"],
    "Users": ["id"],
    "UserGroups": ["id"],
}

# A stable field to partition on — never the incremental cursor (`updatedAt` changes on every
# edit and would rewrite partitions on every sync). Only Connections exposes a stable top-level
# `createdAt`; the rest either have no creation timestamp (Folders/Schedules) or nest it under
# `meta.created` (Users/UserGroups), which isn't worth partitioning on.
PARTITION_KEYS: dict[str, str | None] = {
    "Documents": None,
    "Folders": None,
    "Connections": "createdAt",
    "Schedules": None,
    "Users": None,
    "UserGroups": None,
}

DEFAULT_PAGE_SIZE = 100

# SCIM users/groups endpoints require an Organization API key (Personal Access Tokens are
# explicitly documented as unsupported for them).
SCIM_ENDPOINTS = frozenset({"Users", "UserGroups"})
