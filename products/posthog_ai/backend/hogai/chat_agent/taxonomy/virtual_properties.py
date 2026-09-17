from collections.abc import Container, Iterable
from typing import Literal

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, CoreFilterDefinition

from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType

type VirtualPropertyGroup = Literal["event_properties", "person_properties", "groups"]
type PropertyDefinitionOrVirtual = PropertyDefinition | CoreFilterDefinition


def virtual_group_for_entity(entity: str) -> VirtualPropertyGroup:
    """Map a taxonomy entity name (event, person, or a group type name) to its virtual property group."""
    if entity == "event":
        return "event_properties"
    if entity == "person":
        return "person_properties"
    return "groups"


def get_virtual_property_definition(group: VirtualPropertyGroup, property_name: str) -> CoreFilterDefinition | None:
    definition = CORE_FILTER_DEFINITIONS_BY_GROUP[group].get(property_name)
    if definition is None or definition.get("virtual") is not True:
        return None
    return definition


def list_virtual_properties(group: VirtualPropertyGroup, exclude: Container[str] = ()) -> list[tuple[str, str | None]]:
    """(name, type) pairs for the group's virtual properties, for inclusion in property listings."""
    return [
        (name, definition.get("type"))
        for name, definition in CORE_FILTER_DEFINITIONS_BY_GROUP[group].items()
        if definition.get("virtual") is True and name not in exclude
    ]


def merge_virtual_property_definitions(
    group: VirtualPropertyGroup,
    property_definitions: dict[str, PropertyDefinition],
    property_names: Iterable[str],
) -> dict[str, PropertyDefinitionOrVirtual]:
    merged: dict[str, PropertyDefinitionOrVirtual] = dict(property_definitions)
    for property_name in property_names:
        if property_name in merged:
            continue
        if virtual_definition := get_virtual_property_definition(group, property_name):
            merged[property_name] = virtual_definition
    return merged


def get_property_definition_type(property_definition: PropertyDefinitionOrVirtual) -> str | None:
    if isinstance(property_definition, PropertyDefinition):
        return property_definition.property_type
    return property_definition.get("type")


def property_is_string_like(property_definition: PropertyDefinitionOrVirtual) -> bool:
    return get_property_definition_type(property_definition) in (PropertyType.String, PropertyType.Datetime)


def get_virtual_property_sample_values(
    property_definition: CoreFilterDefinition,
) -> tuple[list[str | int | float], int | None]:
    """Sample values for a virtual property, sourced from the static taxonomy instead of stored data."""
    examples = property_definition.get("examples")
    if examples:
        return examples, None
    if property_definition.get("type") == "Boolean":
        return ["true", "false"], 2
    return [], None


def virtual_property_no_values_message(property_name: str) -> str:
    return (
        f"The property {property_name} is a virtual property computed at query time, "
        "so the taxonomy does not have stored sample values."
    )
