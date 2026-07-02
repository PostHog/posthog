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
    # ProseMirror/TipTap content: usually a `{type: "doc", content: [...]}` dict, but some
    # notebooks (e.g. group/account templates) persist a bare list of nodes. JSONField allows
    # either, so the contract must too.
    content: dict[str, Any] | list[Any] | None
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
class MarkdownNotebookMigrationStats:
    """Markdown migration status for notebooks in an optional team scope."""

    total: int
    converted: int
    pending: int
    team_id: int | None = None


@dataclass(frozen=True)
class MarkdownNotebookMigrationPreview:
    """A dry-run preview of one notebook conversion."""

    short_id: str
    title: str | None
    before_version: int
    markdown_preview: str


@dataclass(frozen=True)
class MarkdownNotebookMigrationResult:
    """Result of a markdown notebook migration run."""

    dry_run: bool
    team_id: int | None
    batch_size: int | None
    total: int
    already_converted: int
    pending_before: int
    pending_after: int
    converted: int
    skipped: int
    errored: int
    previews: list[MarkdownNotebookMigrationPreview] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AccountNote:
    """An internal notebook linked to a customer-analytics account, for context rendering."""

    title: str | None
    short_id: str


@dataclass(frozen=True)
class NotebookUserInfo:
    """The creator/modifier of a notebook — raw user values, mirroring UserBasicSerializer's input."""

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: Any
    role_at_organization: str | None


@dataclass(frozen=True)
class AccountNotebook:
    """A full internal notebook linked to an account, with creator/modifier info.

    The richer counterpart to :class:`AccountNote` — backs the account-notebooks CRUD
    endpoints, where consumers render who created/edited each notebook.
    """

    id: UUID
    short_id: str
    title: str | None
    content: dict[str, Any] | list[Any] | None
    text_content: str | None
    created_at: datetime
    last_modified_at: datetime
    created_by: NotebookUserInfo | None = None
    last_modified_by: NotebookUserInfo | None = None
