"""Frozen contracts for the web_analytics facade — no Django, no DRF."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class UserRef:
    id: int
    email: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class FilterPreset:
    id: UUID
    short_id: str
    name: str
    description: str
    pinned: bool
    deleted: bool
    filters: dict
    created_at: datetime
    last_modified_at: datetime
    created_by: UserRef | None
    last_modified_by: UserRef | None
