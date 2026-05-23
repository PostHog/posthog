"""
Contract types for social_signals.

Stable, framework-free frozen dataclasses defining what this product exposes
to the rest of the codebase. No Django imports — stdlib + pydantic only.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
``is_dataclass()`` compatibility (so ``DataclassSerializer`` keeps working),
plus runtime validation on construction. Structural mistakes from mappers or
internal callers surface at the facade boundary instead of producing malformed
JSON twelve stack frames later.
"""

from dataclasses import field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

# --- Input DTOs ---


@dataclass(frozen=True)
class CreateMentionInput:
    """Normalized payload an adapter emits per inbound social item.

    Adapters convert source-specific JSON into this shape; ingestion logic
    upserts on ``(team_id, source_id, external_id)``.
    """

    team_id: int
    source_id: UUID
    platform: str
    mention_type: str
    external_id: str
    url: str = ""
    content: str = ""
    language: str = ""
    author_handle: str = ""
    author_display_name: str = ""
    author_profile_url: str = ""
    author_followers: int | None = None
    posted_at: datetime | None = None
    engagement: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MentionFilters:
    """Query filters for listing mentions."""

    platform: str | None = None
    status: str | None = None
    search: str | None = None
    posted_after: datetime | None = None
    posted_before: datetime | None = None
    limit: int = 100
    offset: int = 0


# --- Output DTOs ---


@dataclass(frozen=True)
class MentionAnalysis:
    """One analyzer's output for a single mention."""

    id: UUID
    mention_id: UUID
    kind: str
    status: str
    result: dict[str, Any]
    model_used: str
    error: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Mention:
    """A single inbound social mention."""

    id: UUID
    team_id: int
    source_id: UUID
    platform: str
    mention_type: str
    external_id: str
    url: str
    content: str
    language: str
    author_handle: str
    author_display_name: str
    author_profile_url: str
    author_followers: int | None
    posted_at: datetime | None
    captured_at: datetime
    engagement: dict[str, Any]
    status: str
    last_error: str
    updated_at: datetime
    analyses: list[MentionAnalysis] = field(default_factory=list)


@dataclass(frozen=True)
class MentionSource:
    """Per-team configured ingestion endpoint (one row per source kind)."""

    id: UUID
    team_id: int
    kind: str
    enabled: bool
    ingest_token: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IngestResult:
    """Outcome of a single webhook delivery."""

    accepted: int
    skipped: int
