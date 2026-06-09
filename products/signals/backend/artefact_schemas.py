"""Pydantic content schemas for `SignalReportArtefact` rows.

Each `SignalReportArtefact` stores its typed payload as JSON text in `content`. These models
describe the shape of that payload per artefact type and validate it on write. They are kept
deliberately dependency-light (pydantic only) so the API layer can import them without pulling
in the report-research / sandbox machinery.

Status artefacts (judgments, repo selection, suggested reviewers) keep their content shapes
inline at their producers; the schemas here cover the *log* artefact types — the work-log
entries that accumulate on a report — plus the two code artefacts introduced alongside them.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

# Product / type identifier parts must be routing-safe — mirrors the custom-agent identifier
# contract (see custom_agent.schemas.validate_identifier_part), kept inline so this module stays
# dependency-light (pydantic only).
_IDENTIFIER_PART_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class CodeReference(BaseModel):
    """Content schema for a `code_reference` artefact: a contiguous span of source lines."""

    file_path: str = Field(description="Repository-relative path to the referenced file.")
    start_line: int = Field(ge=1, description="First line of the referenced range (1-indexed, inclusive).")
    end_line: int = Field(ge=1, description="Last line of the referenced range (1-indexed, inclusive).")
    contents: str = Field(description="The exact source text of lines start_line through end_line.")
    relevance_note: str = Field(
        description="Short note on why this code is relevant to the report.",
    )

    @field_validator("file_path", "contents", "relevance_note")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @model_validator(mode="after")
    def end_line_must_not_precede_start_line(self) -> CodeReference:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class CodeDiff(BaseModel):
    """Content schema for a `code_diff` artefact: a unified diff for a single file."""

    file_path: str = Field(description="Repository-relative path to the file the diff applies to.")
    diff: str = Field(description="Unified diff (patch) text for the file.")
    relevance_note: str = Field(
        description="Short note on why this diff is relevant to the report.",
    )

    @field_validator("file_path", "diff", "relevance_note")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class LineReference(BaseModel):
    """Content schema for a `line_reference` artefact: a single source line callout (a point).

    Used for tour-style features or to let an agent point at one specific line of behaviour,
    as opposed to `code_reference` which spans a contiguous range.
    """

    file_path: str = Field(description="Repository-relative path to the referenced file.")
    line: int = Field(ge=1, description="The referenced line number (1-indexed).")
    note: str = Field(description="Short note on what this line shows or why it matters.")
    contents: str | None = Field(
        default=None, description="The exact source text of the referenced line, if available."
    )

    @field_validator("file_path", "note")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class PushedBranch(BaseModel):
    """Content schema for a `pushed_branch` artefact: a branch pushed to a remote, no PR opened.

    Represents a proposed change set so the UI can render the full would-be PR diff (branch vs
    base) without an actual pull request existing.
    """

    repository: str = Field(description="GitHub repository the branch was pushed to, as `owner/repo`.")
    branch: str = Field(description="Name of the pushed branch holding the proposed changes.")
    base_branch: str | None = Field(
        default=None, description="Branch to diff against when rendering the change set (e.g. `master`)."
    )
    head_sha: str | None = Field(default=None, description="Commit SHA at the tip of the pushed branch.")
    note: str | None = Field(default=None, description="Short note on what this branch proposes.")

    @field_validator("repository", "branch")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class TaskRunArtefact(BaseModel):
    """Content schema for a `task_run` artefact: a reference to a `tasks.Task` run executed for
    the report (research, implementation, …), surfaced as an entry in the report work log.

    `product` / `type` follow the custom-agent identifier shape: the built-in signals pipeline
    uses `product="signals"` with `type` in `{research, implementation, repo_selection}`, while a
    custom agent supplies its own `identifier()` pair. The artefact is only a pointer — the run's
    logs, status and output are read live from the tasks API by `task_id` / `run_id`.
    """

    task_id: str = Field(description="UUID of the `tasks.Task` this run belongs to.")
    run_id: str | None = Field(default=None, description="UUID of the specific `TaskRun`, if known.")
    product: str = Field(
        description="Product that ran the task — `signals` for the built-in pipeline, or a custom agent's "
        "product identifier."
    )
    type: str = Field(
        description="Task type within the product — e.g. `research` / `implementation` / `repo_selection` "
        "for the signals pipeline, or a custom agent's type identifier."
    )

    @field_validator("task_id")
    @classmethod
    def task_id_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @field_validator("product", "type")
    @classmethod
    def identifier_part_must_be_routing_safe(cls, v: str) -> str:
        normalized = v.strip()
        if not _IDENTIFIER_PART_RE.fullmatch(normalized):
            raise ValueError(
                "must contain only lowercase letters, numbers, underscores, or hyphens, "
                "and must start with a lowercase letter or number"
            )
        return normalized


class NoteArtefact(BaseModel):
    """Content schema for a `note` artefact: a free-form note authored by an agent or by code."""

    note: str = Field(description="The note text (markdown allowed).")
    author: str | None = Field(default=None, description="Optional label for who authored the note.")

    @field_validator("note")
    @classmethod
    def note_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v
