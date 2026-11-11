"""
Contract types for release.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


class ReleaseNotFoundError(Exception):
    pass


class UnknownFeatureFlagsError(Exception):
    def __init__(self, flag_ids: list[int]) -> None:
        super().__init__(flag_ids)
        self.flag_ids = flag_ids


@dataclass(frozen=True)
class FlagVisibility:
    existing: frozenset[int]
    visible: frozenset[int]
    linkable: frozenset[int]

    @property
    def hidden(self) -> frozenset[int]:
        return self.existing - self.visible


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
    has_hidden_flags: bool
    created_at: datetime


@dataclass(frozen=True)
class CreateReleaseInput:
    team_id: int
    name: str
    description: str = ""
    owner_id: int | None = None
    feature_flag_ids: tuple[int, ...] = ()
