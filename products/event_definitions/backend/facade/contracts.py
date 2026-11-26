"""Contract types for event_definitions.

Frozen dataclasses that cross the event_definitions boundary. No Django imports.
"""

from typing import Literal
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import PropertyDefinitionType, PropertyType

# The definition tables that have a team-scoped metadata copy
DefinitionKind = Literal["event", "property"]


@dataclass(frozen=True)
class PlaceholderEventDefinition:
    """An event definition to create before ingestion has seen the event."""

    name: str
    description: str | None = None


@dataclass(frozen=True)
class PropertyDefinition:
    id: UUID
    team_id: int
    project_id: int | None
    name: str
    type: PropertyDefinitionType
    # Set only for `PropertyDefinitionType.GROUP`.
    group_type_index: int | None
    property_type: PropertyType | None
    is_numerical: bool
