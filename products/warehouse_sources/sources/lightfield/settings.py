from dataclasses import dataclass

from products.warehouse_sources.sources.sdk import IncrementalField

# Lightfield caps list-endpoint page size at 25 (`limit` defaults to 25, maximum 25).
LIGHTFIELD_PAGE_SIZE = 25


@dataclass(frozen=True)
class LightfieldFanOutConfig:
    parent_path: str
    # Column that carries the parent id on each child row, since the child rows do not include it.
    parent_key: str
    # Lists hold one object type each, so a member endpoint only reads lists of its own type.
    parent_object_type: str | None = None


@dataclass(frozen=True)
class LightfieldEndpointConfig:
    name: str
    path: str
    # Every read scope the endpoint needs; empty when no single read scope covers it.
    scopes: tuple[str, ...] = ()
    primary_keys: tuple[str, ...] = ("id",)
    # `createdAt` is stable per record; `updatedAt` changes on every write and would
    # rewrite partitions each sync.
    partition_key: str | None = "createdAt"
    # Each page holds only the records the key can read, so a short or empty page does not
    # mean the list is done; these endpoints page until `offset` reaches `totalCount`.
    page_to_total_count: bool = False
    # For a fan-out endpoint, `{id}` in `path` is replaced with each parent record id.
    fan_out: LightfieldFanOutConfig | None = None


def _list_members_endpoint(member_path: str, object_type: str) -> LightfieldEndpointConfig:
    return LightfieldEndpointConfig(
        name=f"list_{member_path}",
        path=f"/v1/lists/{{id}}/{member_path}",
        scopes=("lists:read", f"{member_path}:read"),
        primary_keys=("listId", "id"),
        page_to_total_count=True,
        fan_out=LightfieldFanOutConfig(parent_path="/v1/lists", parent_key="listId", parent_object_type=object_type),
    )


# Lightfield list endpoints only filter with `$fieldSlug[operator]=` on field slugs — there is no
# documented filter on the top-level createdAt/updatedAt record properties and no sort parameter,
# so a reliable server-side incremental cursor cannot be built. Sequences and enrollments filter on
# creation and activity times, but a status change moves none of them, so a filter would miss
# updates. All endpoints are full refresh.
LIGHTFIELD_ENDPOINTS: dict[str, LightfieldEndpointConfig] = {
    "accounts": LightfieldEndpointConfig(name="accounts", path="/v1/accounts", scopes=("accounts:read",)),
    "contacts": LightfieldEndpointConfig(name="contacts", path="/v1/contacts", scopes=("contacts:read",)),
    "opportunities": LightfieldEndpointConfig(
        name="opportunities", path="/v1/opportunities", scopes=("opportunities:read",)
    ),
    "meetings": LightfieldEndpointConfig(name="meetings", path="/v1/meetings", scopes=("meetings:read",)),
    "tasks": LightfieldEndpointConfig(name="tasks", path="/v1/tasks", scopes=("tasks:read",)),
    "notes": LightfieldEndpointConfig(name="notes", path="/v1/notes", scopes=("notes:read",)),
    "lists": LightfieldEndpointConfig(name="lists", path="/v1/lists", scopes=("lists:read",)),
    "members": LightfieldEndpointConfig(name="members", path="/v1/members", scopes=("members:read",)),
    "emails": LightfieldEndpointConfig(name="emails", path="/v1/emails", scopes=("emails:read",)),
    "messages": LightfieldEndpointConfig(
        name="messages", path="/v1/messages", scopes=("messages:read",), page_to_total_count=True
    ),
    "sequences": LightfieldEndpointConfig(
        name="sequences", path="/v1/sequences", scopes=("sequences:read",), page_to_total_count=True
    ),
    "sequence_enrollments": LightfieldEndpointConfig(
        name="sequence_enrollments",
        path="/v1/sequences/{id}/enrollments",
        scopes=("sequences:read",),
        primary_keys=("sequenceId", "id"),
        partition_key="enrolledAt",
        page_to_total_count=True,
        fan_out=LightfieldFanOutConfig(parent_path="/v1/sequences", parent_key="sequenceId"),
    ),
    "list_accounts": _list_members_endpoint("accounts", "account"),
    "list_contacts": _list_members_endpoint("contacts", "contact"),
    "list_opportunities": _list_members_endpoint("opportunities", "opportunity"),
    # Custom object types are discovered at sync time, so every type lands in one table keyed by
    # its `objectType` slug. Record ids are only documented as unique per type.
    "custom_objects": LightfieldEndpointConfig(
        name="custom_objects",
        path="/v1/objects",
        primary_keys=("objectType", "id"),
    ),
    # One row per field or relationship definition, across the standard and custom object types.
    # Relationship definitions already use `objectType` for the related type, so the owning type is
    # `ownerObjectType`.
    "field_definitions": LightfieldEndpointConfig(
        name="field_definitions",
        path="/v1/{resource}/definitions",
        primary_keys=("ownerObjectType", "key"),
        partition_key=None,
    ),
    "relationship_definitions": LightfieldEndpointConfig(
        name="relationship_definitions",
        path="/v1/{resource}/definitions",
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
