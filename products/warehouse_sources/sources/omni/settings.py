from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Documents",
    "Folders",
    "Connections",
    "Schedules",
    "Users",
    "UserGroups",
    "Models",
    "ScheduleRecipients",
    "DocumentPermissions",
    "UserAttributes",
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
    "Models": ["id"],
    "ScheduleRecipients": ["scheduleId"],
    # A principal appears twice when it has both direct and folder-inherited access to a document.
    "DocumentPermissions": ["documentId", "principalId", "accessSource"],
    # System-defined attributes return an empty `id`; `name` is unique within the organization.
    "UserAttributes": ["name"],
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
    "Models": "createdAt",
    "ScheduleRecipients": None,
    "DocumentPermissions": None,
    "UserAttributes": None,
}

DEFAULT_PAGE_SIZE = 100

# SCIM users/groups endpoints require an Organization API key (Personal Access Tokens are
# explicitly documented as unsupported for them).
SCIM_ENDPOINTS = frozenset({"Users", "UserGroups"})

# Child endpoints fetched once per parent row. The parent's sort is pinned to a field that rarely
# changes so cursor pagination doesn't skip rows edited mid-walk (Documents otherwise sorts by
# `updatedAt`).
FANOUT_ENDPOINTS: dict[str, DependentEndpointConfig] = {
    "ScheduleRecipients": DependentEndpointConfig(
        parent_name="Schedules",
        resolve_param="scheduleId",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "scheduleId"},
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    ),
    "DocumentPermissions": DependentEndpointConfig(
        parent_name="Documents",
        resolve_param="documentId",
        resolve_field="identifier",
        include_from_parent=["identifier"],
        parent_field_renames={"identifier": "documentId"},
        parent_params={"sortField": "name", "sortDirection": "asc"},
        # The access list needs Manager permission on each document, so a key that can view a
        # document but not manage it gets a 403 for that document only.
        child_response_actions=[
            {"status_code": 403, "action": "ignore"},
            {"status_code": 404, "action": "ignore"},
        ],
    ),
}
