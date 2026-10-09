from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField

# Lightfield caps list-endpoint page size at 25 (`limit` defaults to 25, maximum 25).
LIGHTFIELD_PAGE_SIZE = 25


@dataclass(frozen=True)
class LightfieldEndpointConfig:
    name: str
    path: str
    # None when no single read scope covers the endpoint.
    scope: str | None
    primary_keys: tuple[str, ...] = ("id",)
    # `createdAt` is stable per record; `updatedAt` changes on every write and would
    # rewrite partitions each sync.
    partition_key: str | None = "createdAt"


# Lightfield list endpoints only filter with `$fieldSlug[operator]=` on field slugs — there is no
# documented filter on the top-level createdAt/updatedAt record properties and no sort parameter,
# so a reliable server-side incremental cursor cannot be built. All endpoints are full refresh.
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
    # Custom object types are discovered at sync time, so every type lands in one table keyed by
    # its `objectType` slug. Record ids are only documented as unique per type.
    "custom_objects": LightfieldEndpointConfig(
        name="custom_objects",
        path="/v1/objects",
        scope=None,
        primary_keys=("objectType", "id"),
    ),
    # One row per field or relationship definition, across the standard and custom object types.
    # Relationship definitions already use `objectType` for the related type, so the owning type is
    # `ownerObjectType`.
    "field_definitions": LightfieldEndpointConfig(
        name="field_definitions",
        path="/v1/{resource}/definitions",
        scope=None,
        primary_keys=("ownerObjectType", "key"),
        partition_key=None,
    ),
    "relationship_definitions": LightfieldEndpointConfig(
        name="relationship_definitions",
        path="/v1/{resource}/definitions",
        scope=None,
        primary_keys=("ownerObjectType", "key"),
        partition_key=None,
    ),
}

CUSTOM_OBJECTS_ENDPOINT = "custom_objects"

# Definitions table name -> the map in the `/definitions` response it flattens.
DEFINITION_ENDPOINTS: dict[str, str] = {
    "field_definitions": "fieldDefinitions",
    "relationship_definitions": "relationshipDefinitions",
}


@dataclass(frozen=True)
class LightfieldDefinitionResource:
    object_type: str
    path: str


# Standard object types with a `/definitions` endpoint. Lists, members, and emails have none.
STANDARD_DEFINITION_RESOURCES: tuple[LightfieldDefinitionResource, ...] = (
    LightfieldDefinitionResource(object_type="account", path="/v1/accounts/definitions"),
    LightfieldDefinitionResource(object_type="contact", path="/v1/contacts/definitions"),
    LightfieldDefinitionResource(object_type="opportunity", path="/v1/opportunities/definitions"),
    LightfieldDefinitionResource(object_type="meeting", path="/v1/meetings/definitions"),
    LightfieldDefinitionResource(object_type="task", path="/v1/tasks/definitions"),
    LightfieldDefinitionResource(object_type="note", path="/v1/notes/definitions"),
)

ENDPOINTS = tuple(LIGHTFIELD_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter (see the note above), so nothing is
# advertised as an incremental candidate.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
