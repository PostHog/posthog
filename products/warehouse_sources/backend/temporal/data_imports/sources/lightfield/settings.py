from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField

# Lightfield caps list-endpoint page size at 25 (`limit` defaults to 25, maximum 25).
LIGHTFIELD_PAGE_SIZE = 25


@dataclass
class LightfieldEndpointConfig:
    name: str
    path: str
    scope: str
    primary_key: str = "id"
    # `createdAt` is stable per record; `updatedAt` changes on every write and would
    # rewrite partitions each sync.
    partition_key: str = "createdAt"


# Lightfield list endpoints only filter with `$fieldSlug[operator]=` on field slugs — there is no
# documented filter on the top-level createdAt/updatedAt record properties and no sort parameter,
# so a reliable server-side incremental cursor cannot be built. All endpoints are full refresh.
#
# Custom objects (`/v1/objects/{entitySlug}`) are deliberately not included: enumerating them
# requires a live `listDefinitions` call at schema discovery, and the feature is plan-gated.
LIGHTFIELD_ENDPOINTS: dict[str, LightfieldEndpointConfig] = {
    "accounts": LightfieldEndpointConfig(name="accounts", path="/v1/accounts", scope="accounts:read"),
    "contacts": LightfieldEndpointConfig(name="contacts", path="/v1/contacts", scope="contacts:read"),
    "opportunities": LightfieldEndpointConfig(
        name="opportunities", path="/v1/opportunities", scope="opportunities:read"
    ),
    "meetings": LightfieldEndpointConfig(name="meetings", path="/v1/meetings", scope="meetings:read"),
    "tasks": LightfieldEndpointConfig(name="tasks", path="/v1/tasks", scope="tasks:read"),
    "notes": LightfieldEndpointConfig(name="notes", path="/v1/notes", scope="notes:read"),
    "lists": LightfieldEndpointConfig(name="lists", path="/v1/lists", scope="lists:read"),
    "members": LightfieldEndpointConfig(name="members", path="/v1/members", scope="members:read"),
    "emails": LightfieldEndpointConfig(name="emails", path="/v1/emails", scope="emails:read"),
}

ENDPOINTS = tuple(LIGHTFIELD_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter (see the note above), so nothing is
# advertised as an incremental candidate.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
