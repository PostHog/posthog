"""
Facade for groups.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..logic import group_types
from ..logic.property_definitions import create_property_definition
from ..logic.related_actors_query import RelatedActorsQuery
from . import contracts

if TYPE_CHECKING:
    from posthog.hogql_queries.serialized_actors import SerializedActor
    from posthog.models import Team
    from posthog.models.property import GroupTypeIndex


def get_related_actors(
    team: Team, group_type_index: GroupTypeIndex | str | None, actor_id: str
) -> list[SerializedActor]:
    return RelatedActorsQuery(team, group_type_index, actor_id).run()


def upsert_group_property_definition(input: contracts.GroupPropertyDefinitionInput) -> None:
    create_property_definition(
        team_id=input.team_id,
        project_id=input.project_id,
        group_type_index=input.group_type_index,
        property_name=input.property_name,
        property_value=input.property_value,
    )


def list_group_types(project_id: int) -> list[contracts.GroupType]:
    """Raises GroupTypesUnavailable when personhog does not answer."""
    return group_types.read_group_types(project_id)


def get_group_type(project_id: int, index: int) -> contracts.GroupType:
    """Raises GroupTypeNotFound for an index the project does not use, and GroupTypesUnavailable."""
    return group_types.read_group_type(project_id, index)


def group_type_changes(current: contracts.GroupType, edit: contracts.GroupTypeEdit) -> list[str]:
    return group_types.changed_fields(current, edit)


def group_type_fingerprint(group_type: contracts.GroupType) -> str:
    """A hash of the editable fields, for update_group_type to check that nothing changed since staff read them."""
    return group_types.fingerprint(group_type)


def update_group_type(project_id: int, index: int, edit: contracts.GroupTypeEdit, baseline: str) -> contracts.GroupType:
    """Saves the fields that differ from what is stored and returns the group type as it was before.

    Raises GroupTypeChanged when the stored group type no longer matches the baseline fingerprint, else like
    get_group_type.
    """
    return group_types.update_group_type(project_id, index, edit, baseline)
