"""
Contract types for release.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


class ReleaseNotFoundError(Exception):
    pass


class UnknownLinkedObjectsError(Exception):
    def __init__(self, field: str, noun: str, ids: list[Any]) -> None:
        super().__init__(field, ids)
        self.field = field
        self.noun = noun
        self.ids = ids


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
class LinkedSurveyDTO:
    id: UUID
    name: str
    created_at: datetime
    start_date: datetime | None
    end_date: datetime | None
    linked_flag_id: int | None
    archived: bool


@dataclass(frozen=True)
class SurveyVisibility:
    existing: frozenset[UUID]
    visible: frozenset[UUID]
    linkable: frozenset[UUID]
    summaries: tuple[LinkedSurveyDTO, ...] = ()

    @property
    def hidden(self) -> frozenset[UUID]:
        return self.existing - self.visible


@dataclass(frozen=True)
class LinkedInsightDTO:
    id: int
    short_id: str
    name: str
    created_at: datetime | None
    last_modified_at: datetime | None
    deleted: bool


@dataclass(frozen=True)
class InsightVisibility:
    existing: frozenset[int]
    visible: frozenset[int]
    linkable: frozenset[int]
    summaries: tuple[LinkedInsightDTO, ...] = ()

    @property
    def hidden(self) -> frozenset[int]:
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
    survey_ids: list[UUID]
    surveys: list[LinkedSurveyDTO]
    insight_ids: list[int]
    insights: list[LinkedInsightDTO]
    created_at: datetime


@dataclass(frozen=True)
class CreateReleaseInput:
    team_id: int
    name: str
    description: str = ""
    owner_id: int | None = None
    feature_flag_ids: tuple[int, ...] = ()
    broadcast_ids: tuple[UUID, ...] = ()
    survey_ids: tuple[UUID, ...] = ()
    insight_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ImportFlag:
    id: int
    key: str
