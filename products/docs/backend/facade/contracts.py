"""
Contract types for docs.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib
variant — same syntax, same ``is_dataclass()`` compatibility (so
``DataclassSerializer`` keeps working), but with runtime type
validation on construction.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import SplineStatus


@dataclass(frozen=True)
class SplineReticulatorDTO:
    id: UUID
    name: str
    status: SplineStatus
    created_at: datetime


@dataclass(frozen=True)
class CreateSplineReticulatorInput:
    team_id: int
    name: str
