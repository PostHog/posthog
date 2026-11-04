"""Facade for event_definitions.

The only module other products and core may import, besides `contracts`, `enums` and the
`testing` door. Functions accept and return contracts, call `logic/`, and never hand out ORM
instances or querysets.
"""

from collections.abc import Callable, Sequence

from ..logic import event_property_purge, placeholder, property_definitions
from . import contracts
from .enums import PropertyDefinitionType, PropertyType


def create_placeholder_event_definitions(
    *, team_id: int, definitions: Sequence[contracts.PlaceholderEventDefinition]
) -> None:
    """Create event definitions that ingestion can claim when the events are first seen."""
    placeholder.create_placeholder_event_definitions(team_id=team_id, definitions=definitions)


def delete_event_properties_for_team(
    team_id: int, should_stop: Callable[[], bool] | None = None, batch_size: int = 10000
) -> bool:
    """Delete the team's event properties in batches. Return False when `should_stop` ended the purge first."""
    return event_property_purge.delete_event_properties_for_team(
        team_id, should_stop=should_stop, batch_size=batch_size
    )


def upsert_group_property_definition(
    *, team_id: int, project_id: int, group_type_index: int, name: str, property_type: PropertyType
) -> None:
    """Create the project's definition of a group property, or update the type of the existing one."""
    property_definitions.upsert_group_property_definition(
        team_id=team_id,
        project_id=project_id,
        group_type_index=group_type_index,
        name=name,
        property_type=property_type,
    )


def get_property_type(
    *, project_id: int, name: str, type: PropertyDefinitionType, group_type_index: int | None = None
) -> PropertyType | None:
    """The value type the project's definition of a property records.

    Returns None when the project has no such definition, or the definition has no type yet.
    `group_type_index` is read only for `PropertyDefinitionType.GROUP`.
    """
    return property_definitions.get_property_type(
        project_id=project_id, name=name, type=type, group_type_index=group_type_index
    )
