import json
import hashlib
from typing import Any

import structlog

from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.personhog_client import consistency_to_read_options
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdRequest, UpdateGroupTypeMappingRequest

from products.groups.backend.facade.contracts import (
    GroupType,
    GroupTypeChanged,
    GroupTypeEdit,
    GroupTypeNotFound,
    GroupTypesUnavailable,
)

CALLER_TAG = "groups/staff_console"
EDITABLE_FIELDS = ["name_singular", "name_plural", "default_columns", "created_at"]

logger = structlog.get_logger(__name__)


def _group_type(mapping: dict[str, Any]) -> GroupType:
    return GroupType(
        index=mapping["group_type_index"],
        group_type=mapping["group_type"],
        name_singular=mapping["name_singular"] or "",
        name_plural=mapping["name_plural"] or "",
        default_columns=mapping["default_columns"],
        created_at=mapping["created_at"],
    )


def read_group_types(project_id: int) -> list[GroupType]:
    # A strong read, so a form that staff save next starts from what personhog holds, not from a lagging replica.
    def fetch() -> list[GroupType]:
        response = require_personhog_client().get_group_type_mappings_by_project_id(
            GetGroupTypeMappingsByProjectIdRequest(
                project_id=project_id, read_options=consistency_to_read_options("strong")
            )
        )
        return [_group_type(proto_group_type_mapping_to_dict(mapping)) for mapping in response.mappings]

    group_types = personhog_call("read_group_types", fetch, caller_tag=CALLER_TAG, reraise_as=GroupTypesUnavailable)
    return sorted(group_types, key=lambda group_type: group_type.index)


def read_group_type(project_id: int, index: int) -> GroupType:
    for group_type in read_group_types(project_id):
        if group_type.index == index:
            return group_type
    raise GroupTypeNotFound(f"Project {project_id} has no group type with index {index}")


def changed_fields(current: GroupType, edit: GroupTypeEdit) -> list[str]:
    return [field for field in EDITABLE_FIELDS if getattr(current, field) != getattr(edit, field)]


def _field_values(item: GroupType | GroupTypeEdit, fields: list[str]) -> dict[str, Any]:
    values = {field: getattr(item, field) for field in fields}
    if values.get("created_at") is not None:
        values["created_at"] = values["created_at"].isoformat()
    return values


def fingerprint(group_type: GroupType) -> str:
    values = json.dumps(_field_values(group_type, EDITABLE_FIELDS), sort_keys=True)
    return hashlib.sha256(values.encode()).hexdigest()


def update_group_type(project_id: int, index: int, edit: GroupTypeEdit, baseline: str) -> GroupType:
    """Writes the fields that differ from what personhog holds now, and returns the group type as it was before.

    The edit carries every editable field, so it would also write back the old value of a field that changed
    after staff read the group type. A baseline fingerprint that no longer matches the stored row refuses that.
    """
    previous = read_group_type(project_id, index)
    if fingerprint(previous) != baseline:
        raise GroupTypeChanged(f"Group type {index} of project {project_id} changed since it was read")
    fields = changed_fields(previous, edit)
    if not fields:
        return previous

    # A field in the update mask without a value tells personhog to set the column to null.
    request: dict[str, Any] = {"project_id": project_id, "group_type_index": index, "update_mask": fields}
    if "name_singular" in fields:
        request["name_singular"] = edit.name_singular
    if "name_plural" in fields:
        request["name_plural"] = edit.name_plural
    if "default_columns" in fields and edit.default_columns is not None:
        request["default_columns"] = json.dumps(edit.default_columns).encode()
    if "created_at" in fields and edit.created_at is not None:
        request["created_at"] = int(edit.created_at.timestamp() * 1000)

    personhog_call(
        "update_group_type",
        lambda: require_personhog_client().update_group_type_mapping(UpdateGroupTypeMappingRequest(**request)),
        caller_tag=CALLER_TAG,
        reraise_as=GroupTypesUnavailable,
    )
    invalidate_group_types_cache(project_id)
    # Personhog keeps no history, so this line is the only record of the old values that an undo needs.
    logger.info(
        "group_type_updated",
        project_id=project_id,
        group_type_index=index,
        fields=fields,
        before=_field_values(previous, fields),
        after=_field_values(edit, fields),
    )
    return previous
