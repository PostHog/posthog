"""Event definitions facade: existence checks other products use to detect schema drift."""

from collections.abc import Iterable

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import PropertyDefinition

PROPERTY_TYPES_BY_NAME = {label: value for value, label in PropertyDefinition.Type.choices}


def existing_event_names(team_id: int, names: Iterable[str]) -> set[str]:
    """The subset of ``names`` that are defined events in this team."""
    wanted = set(names)
    if not wanted:
        return set()
    return set(EventDefinition.objects.filter(team_id=team_id, name__in=wanted).values_list("name", flat=True))


def existing_property_names(team_id: int, names: Iterable[str], property_type: str) -> set[str]:
    """The subset of ``names`` defined as properties of ``property_type`` ('event', 'person', ...) in this team."""
    wanted = set(names)
    type_value = PROPERTY_TYPES_BY_NAME.get(property_type)
    if not wanted or type_value is None:
        return set()
    return set(
        PropertyDefinition.objects.filter(team_id=team_id, type=type_value, name__in=wanted).values_list(
            "name", flat=True
        )
    )
