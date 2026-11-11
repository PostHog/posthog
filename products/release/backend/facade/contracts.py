"""
Contract types for release.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseOwnerDTO:
    id: int
    first_name: str


@dataclass(frozen=True)
class ReleaseDTO:
    id: UUID
    name: str
    description: str
    owner: ReleaseOwnerDTO | None
    feature_flag_ids: list[int]
    created_at: datetime


@dataclass(frozen=True)
class CreateReleaseInput:
    team_id: int
    name: str
    description: str = ""
    owner_id: int | None = None
    feature_flag_ids: tuple[int, ...] = ()
