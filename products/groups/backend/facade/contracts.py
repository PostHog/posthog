"""
Contract types for groups.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from pydantic import JsonValue
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class GroupPropertyDefinitionInput:
    team_id: int
    project_id: int
    group_type_index: int
    property_name: str
    property_value: JsonValue
