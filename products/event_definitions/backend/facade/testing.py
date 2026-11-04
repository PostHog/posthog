"""Test-support facade for event_definitions.

Suites outside this product plant and read definition rows through here instead of importing the
models.
"""

from ..models.property_definition import PropertyDefinition as PropertyDefinitionModel
from . import contracts
from .enums import PropertyDefinitionType, PropertyType

__all__ = [
    "create_property_definition",
    "find_property_definitions",
    "property_definition_exists",
    "set_property_type",
]


def _to_property_definition(instance: PropertyDefinitionModel) -> contracts.PropertyDefinition:
    return contracts.PropertyDefinition(
        id=instance.id,
        team_id=instance.team_id,
        project_id=instance.project_id,
        name=instance.name,
        type=PropertyDefinitionType(instance.type),
        group_type_index=instance.group_type_index,
        property_type=PropertyType(instance.property_type) if instance.property_type else None,
        is_numerical=instance.is_numerical,
    )


def create_property_definition(
    *,
    team_id: int,
    name: str,
    type: PropertyDefinitionType = PropertyDefinitionType.EVENT,
    property_type: PropertyType | None = None,
    group_type_index: int | None = None,
    is_numerical: bool = False,
    project_id: int | None = None,
) -> contracts.PropertyDefinition:
    """Create a property definition. `project_id` stays empty unless given, as ingestion leaves it on older rows."""
    instance = PropertyDefinitionModel.objects.create(
        team_id=team_id,
        project_id=project_id,
        name=name,
        type=type,
        property_type=property_type,
        group_type_index=group_type_index,
        is_numerical=is_numerical,
    )
    return _to_property_definition(instance)


def property_definition_exists(*, team_id: int, name: str) -> bool:
    """Whether the team has a definition of any type with this name."""
    return PropertyDefinitionModel.objects.filter(team_id=team_id, name=name).exists()


def set_property_type(*, team_id: int, name: str, property_type: PropertyType | None) -> None:
    """Change the value type of the team's only definition with this name."""
    instance = PropertyDefinitionModel.objects.get(team_id=team_id, name=name)
    instance.property_type = property_type
    instance.save()


def find_property_definitions(
    *,
    team_id: int | None = None,
    project_id: int | None = None,
    name: str | None = None,
    type: PropertyDefinitionType | None = None,
    group_type_index: int | None = None,
) -> list[contracts.PropertyDefinition]:
    """The definitions that match every filter given, ordered by name. A filter left as None matches anything."""
    filters = {
        "team_id": team_id,
        "project_id": project_id,
        "name": name,
        "type": type,
        "group_type_index": group_type_index,
    }
    queryset = PropertyDefinitionModel.objects.filter(
        **{field: value for field, value in filters.items() if value is not None}
    )
    return [_to_property_definition(instance) for instance in queryset.order_by("name", "id")]
