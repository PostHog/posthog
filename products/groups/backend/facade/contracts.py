"""
Contract types for groups.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime

from pydantic import JsonValue
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class GroupPropertyDefinitionInput:
    team_id: int
    project_id: int
    group_type_index: int
    property_name: str
    property_value: JsonValue


@dataclass(frozen=True)
class GroupType:
    """A group type of a project, as personhog stores it. An unset name is an empty string."""

    index: int
    group_type: str
    name_singular: str
    name_plural: str
    default_columns: list[str] | None
    # HogQL leaves this group off events from before this time.
    created_at: datetime | None


@dataclass(frozen=True)
class GroupTypeEdit:
    """The editable fields of a group type, with the values staff want them to have."""

    name_singular: str
    name_plural: str
    default_columns: list[str] | None
    created_at: datetime | None


class GroupTypesUnavailable(Exception):
    pass


class GroupTypeNotFound(Exception):
    pass


class GroupTypeChanged(Exception):
    pass
