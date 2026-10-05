"""Snapshots of a taxonomy definition for the activity log.

The API deletes a definition row from Postgres outright, so the activity row is the only
record of what the definition held. Support reads that row during an account-compromise or
mistaken-delete review, and the row has to say enough to rebuild the definition by hand.
"""

from typing import Any

from posthog.api.tagged_item import current_tag_names

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import PropertyDefinition

# Only present on the enterprise subclasses, so each is read with a default.
_EVENT_DEFINITION_ENTERPRISE_FIELDS = ("description", "owner", "verified", "hidden", "default_columns")
_PROPERTY_DEFINITION_ENTERPRISE_FIELDS = ("description", "verified", "hidden")


def _with_enterprise_fields(state: dict[str, Any], instance: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    for field in fields:
        value = getattr(instance, field, None)
        if value is not None:
            state[field] = value
    return state


def event_definition_state(instance: EventDefinition) -> dict[str, Any]:
    """The event definition fields a person needs to recreate the definition."""
    state: dict[str, Any] = {
        "name": instance.name,
        "tags": sorted(current_tag_names(instance)),
        "enforcement_mode": instance.enforcement_mode,
        "primary_property": instance.primary_property,
    }
    return _with_enterprise_fields(state, instance, _EVENT_DEFINITION_ENTERPRISE_FIELDS)


def property_definition_state(instance: PropertyDefinition) -> dict[str, Any]:
    """The property definition fields a person needs to recreate the definition."""
    state: dict[str, Any] = {
        "name": instance.name,
        "tags": sorted(current_tag_names(instance)),
        "property_type": instance.property_type,
        "is_numerical": instance.is_numerical,
        "group_type_index": instance.group_type_index,
    }
    return _with_enterprise_fields(state, instance, _PROPERTY_DEFINITION_ENTERPRISE_FIELDS)
