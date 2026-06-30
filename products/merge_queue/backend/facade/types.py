"""Shared facade types.

Plain stdlib dataclasses/enums: the facade is the only surface that Cowboy, the
surfaces, and the shadow harness import, so it carries no Django imports.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ActorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    COWBOY = "cowboy"
    SYSTEM = "system"


@dataclass(frozen=True)
class Actor:
    id: str
    kind: ActorKind
    display: str = ""

    @property
    def is_human(self) -> bool:
        return self.kind is ActorKind.HUMAN


@dataclass(frozen=True)
class PRRef:
    repo: str  # "owner/name"
    number: int
    head_sha: str


@dataclass(frozen=True)
class Scope:
    partition: str | None  # None = whole queue

    @classmethod
    def queue(cls) -> "Scope":
        return cls(partition=None)

    @classmethod
    def of(cls, name: str) -> "Scope":
        return cls(partition=name)


@dataclass(frozen=True)
class SlotStatus:
    partition: str
    state: str  # SlotState value
    position: int  # 0-based index in the partition line
    current_trial_id: UUID | None
    projected_base_sha: str | None


@dataclass(frozen=True)
class EnrollmentStatus:
    pr: PRRef
    state: str  # EnrollmentState value
    slots: list[SlotStatus]
    enrolled_by: Actor
    blocked_by: PRRef | None  # unlanded stack parent, if held
    eject_count: int
    cycle_count: int
    enrolled_at: datetime
