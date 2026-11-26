"""
Contract types for hogs.

Frozen dataclasses that define what this product exposes. No Django imports.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import (
    HogActionStatus,
    HogEvidenceKind,
    HogMessageAuthor,
    HogReportFollowUp,
    HogReportPriority,
    HogReportStatus,
    HogRuleEffect,
    HogStatus,
)


@dataclass(frozen=True)
class HogScheduleDTO:
    id: UUID
    hog_id: UUID
    prompt: str
    cron_expression: str | None
    next_fire_at: datetime | None
    last_fired_at: datetime | None
    enabled: bool
    created_at: datetime


@dataclass(frozen=True)
class HogEvidenceDTO:
    description: str
    source: str
    kind: HogEvidenceKind = HogEvidenceKind.OTHER


@dataclass(frozen=True)
class HogReportDTO:
    id: UUID
    hog_id: UUID
    hog_name: str
    hog_emoji: str
    hog_color: str
    title: str
    summary: str
    priority: HogReportPriority
    impact: str
    proposal: str
    evidence: list[HogEvidenceDTO]
    status: HogReportStatus
    verdict_reason: str
    read: bool
    created_at: datetime
    follow_up: HogReportFollowUp | None = None


@dataclass(frozen=True)
class HogActionDTO:
    id: UUID
    hog_id: UUID
    hog_name: str
    hog_emoji: str
    hog_color: str
    kind: str
    label: str
    draft: str
    status: HogActionStatus
    result: str
    created_at: datetime
    decided_at: datetime | None = None


@dataclass(frozen=True)
class HogMessageDTO:
    id: UUID
    hog_id: UUID
    author: HogMessageAuthor
    content: str
    in_chat: bool
    created_at: datetime
    from_hog_id: UUID | None = None
    from_hog_name: str | None = None
    delivered_at: datetime | None = None
    seen_at: datetime | None = None
    read_at: datetime | None = None
    report: HogReportDTO | None = None
    action: HogActionDTO | None = None


@dataclass(frozen=True)
class HogDTO:
    id: UUID
    name: str
    emoji: str
    color: str
    responsibility: str
    memory: str
    status: HogStatus
    mcp_installation_ids: list[str]
    working: bool
    unread_count: int
    needs_you_count: int
    created_at: datetime
    last_message: HogMessageDTO | None = None


@dataclass(frozen=True)
class HogRuleDTO:
    id: UUID
    hog_id: UUID
    kind: str
    effect: HogRuleEffect


@dataclass(frozen=True)
class HogTriggerDTO:
    id: UUID
    hog_id: UUID
    name: str
    instructions: str
    fire_path: str
    fire_count: int
    last_fired_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class HogEventDTO:
    id: UUID
    trigger_id: UUID
    woke_hog: bool
    created_at: datetime
