"""
Contract types for release.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from posthog.enums import LabeledStrEnum


class ReleaseNotFoundError(Exception):
    pass


class UnknownFeatureFlagsError(Exception):
    def __init__(self, flag_ids: list[int]) -> None:
        super().__init__(flag_ids)
        self.flag_ids = flag_ids


class UnknownBroadcastsError(Exception):
    def __init__(self, broadcast_ids: list[UUID]) -> None:
        super().__init__(broadcast_ids)
        self.broadcast_ids = broadcast_ids


@dataclass(frozen=True)
class LinkedSendDTO:
    id: UUID
    status: str
    created_at: datetime


@dataclass(frozen=True)
class LinkedBroadcastDTO:
    id: UUID
    name: str
    status: str
    recent_sends: list[LinkedSendDTO]


@dataclass(frozen=True)
class BroadcastVisibility:
    existing: frozenset[UUID]
    visible: frozenset[UUID]
    linkable: frozenset[UUID]
    summaries: tuple[LinkedBroadcastDTO, ...] = ()

    @property
    def hidden(self) -> frozenset[UUID]:
        return self.existing - self.visible


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
    broadcast_ids: list[UUID]
    broadcasts: list[LinkedBroadcastDTO]
    created_at: datetime


@dataclass(frozen=True)
class CreateReleaseInput:
    team_id: int
    name: str
    description: str = ""
    owner_id: int | None = None
    feature_flag_ids: tuple[int, ...] = ()
    broadcast_ids: tuple[UUID, ...] = ()


class ImportReason(LabeledStrEnum):
    EXPERIMENT = "experiment", "Experiment"
    EARLY_ACCESS = "early_access", "Early access"
    RELATED_FLAGS = "related_flags", "Related flags"
    FLAG = "flag", "Flag"


@dataclass(frozen=True)
class ImportFlag:
    id: int
    key: str
    created_at: datetime
    created_by_id: int | None
    experiment_names: tuple[str, ...] = ()
    early_access_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportCandidateDTO:
    key: str
    name: str
    reason: ImportReason
    feature_flag_ids: list[int]
    flag_keys: list[str]
    created_at: datetime
