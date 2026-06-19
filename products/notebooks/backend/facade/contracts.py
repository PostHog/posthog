"""
Contract types for notebooks.

Stable, framework-free frozen dataclasses that define what this product exposes
to the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax, same ``is_dataclass()`` compatibility, but with runtime validation on
construction so structural mistakes from mappers surface at the facade boundary
instead of producing a malformed payload further down the call stack.
"""

from dataclasses import field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NotebookData:
    """A notebook's persisted state, as other products read it."""

    id: UUID
    short_id: str
    title: str | None
    content: dict[str, Any] | None
    text_content: str | None
    deleted: bool
    visibility: str
    version: int
    created_at: datetime
    last_modified_at: datetime
    created_by_id: int | None = None
    last_modified_by_id: int | None = None


@dataclass(frozen=True)
class NotebookRecent:
    """A single entry in a team's recently-modified notebooks list."""

    short_id: str
    title: str | None
    last_modified_at: datetime | None


@dataclass(frozen=True)
class NotebookActivitySummary:
    """Aggregate notebook activity for a team — total count plus the most recent few."""

    total_count: int
    recent: list[NotebookRecent] = field(default_factory=list)


@dataclass(frozen=True)
class AccountNote:
    """An internal notebook linked to a customer-analytics account, for context rendering."""

    title: str | None
    short_id: str
