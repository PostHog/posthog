"""
Facade for groups.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
