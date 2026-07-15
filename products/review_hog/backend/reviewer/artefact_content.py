"""Pydantic content schemas + registry for `ReviewReportArtefact` rows.

Mirrors Signals' `artefact_schemas` leaf: one model per artefact type, parsed at the boundary via
`parse_artefact_content` and passed around typed; the row's type is derived from the content
model's class so type and content can never diverge.

ReviewHog owns its own registry and helpers — Signals' `artefact_type_for` / `parse_artefact_content`
close over Signals' module-global registry and cannot take ours — but reuses the content models
that fit unchanged (`Commit`, `CodeReference`, `TaskRunArtefact`, `NoteArtefact`) and the shared
`ArtefactContentValidationError` from the Signals leaf.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import BaseModel, Field, ValidationError, field_validator

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.perspective_selection import PerspectiveSelection
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    CodeReference,
    Commit,
    NoteArtefact,
    TaskRunArtefact,
)

# Mirrors `IssueValidation.category` (the live LLM contract); redefined here so the durable
# artefact shape doesn't drift with the regenerated review-tool schema.
ReviewIssueCategory = Literal[
    "bug",
    "security",
    "performance",
    "code_quality",
    "best_practice",
    "documentation",
    "testing",
    "accessibility",
    "compatibility",
]


class ReviewIssueFinding(BaseModel):
    """Content schema for an `issue_finding` artefact: one durable review finding.

    `issue_key` is turn-local (`run_index`-prefixed so a later turn's reused id can't collide);
    `run_index` lets publishing scope to one turn instead of replaying the whole history.
    """

    issue_key: str = Field(description="Identity within a turn (run_index + file + anchor + perspective + id).")
    run_index: int = Field(
        description="The review turn (1-based) that produced this finding; scopes publishing to one turn."
    )
    title: str = Field(description="Issue title.")
    file: str = Field(description="Repository-relative path to the file containing the issue.")
    lines: list[LineRange] = Field(default_factory=list, description="Affected line ranges.")
    body: str = Field(description="Description of the problem.")
    suggestion: str = Field(description="Specific fix or improvement.")
    priority: IssuePriority = Field(description="Priority level of the finding.")
    source_perspective: str | None = Field(default=None, description="Which review perspective produced this finding.")
    is_directly_related_to_changes: bool = Field(
        default=False, description="Whether the finding is caused by the PR's changes, not just the same file."
    )

    @field_validator("issue_key", "title", "file", "body", "suggestion")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class ValidationVerdict(BaseModel):
    """Content schema for a `validation_verdict` artefact: the validator's ruling on a finding.

    Keyed to its finding by `issue_key`; the latest verdict per key wins.
    """

    issue_key: str = Field(description="The `ReviewIssueFinding.issue_key` this verdict rules on.")
    is_valid: bool = Field(description="Whether the finding should be implemented (true) or dismissed (false).")
    category: ReviewIssueCategory | None = Field(default=None, description="Category of the finding.")
    argumentation: str = Field(description="Why the finding is valid or should be dismissed.")
    adjusted_priority: IssuePriority | None = Field(
        default=None,
        description="Validator's priority override for the finding; null keeps the reviewer's priority.",
    )

    @field_validator("issue_key", "argumentation")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class ChunkSetArtefact(BaseModel):
    """Content for a `chunk_set` artefact: the PR's chunking computed for ONE review turn.

    Per-turn working state, not a cross-turn-stable finding — so it embeds the live `Chunk`
    pipeline model directly (re-derived whenever the head moves) rather than redefining a frozen
    shape. `head_sha` scopes it to its turn, so a resumed run reuses only the current head's
    chunking and a new head re-chunks.
    """

    head_sha: str = Field(description="PR head commit this chunking was computed for (the turn key).")
    chunks: list[Chunk] = Field(description="The reviewable chunks for this turn.")


class PerspectiveSelectionArtefact(BaseModel):
    """Content for a `perspective_selection` artefact: the selector's per-chunk perspective picks.

    Per-turn working state like `chunk_set`: `head_sha` scopes it so a resumed run reuses the
    selection instead of re-paying the one-shot, and a new head re-selects. `selection` is the
    NORMALIZED plan (the exact (perspective, chunk) pairs the fan-out runs), and `roster` is the
    run's full enabled menu — together they let the progress estimate and the skipped-perspective
    UI compute what ran and what was skipped without re-deriving run-time state.
    """

    head_sha: str = Field(description="PR head commit this selection was computed for (the turn key).")
    roster: list[str] = Field(
        default_factory=list, description="Every enabled perspective the selector chose from, in pass order."
    )
    selection: PerspectiveSelection = Field(description="Per-chunk perspective picks with reasons (normalized).")


class PerspectiveResultArtefact(BaseModel):
    """Content for a `perspective_result` artefact: one (perspective, chunk) review for one turn."""

    head_sha: str = Field(description="PR head commit this review was computed for.")
    pass_number: int = Field(description="The review perspective (1=Logic, 2=Contracts, 3=Performance).")
    chunk_id: int = Field(description="The chunk this perspective reviewed.")
    review: IssuesReview = Field(description="The issues this perspective found in this chunk.")


class PRSnapshotArtefact(BaseModel):
    """Content for a `pr_snapshot` artefact: the turn's fetched PR inputs, stored by reference.

    Persisted once at fetch so the Temporal stage activities reload the PR metadata / comments /
    files from the DB by `(report_id, head_sha)` instead of crossing the workflow boundary with the
    big `pr_files` payload (subject to Temporal's ~2 MiB cap). Per-turn working state — head_sha
    scopes it to its turn, latest-wins on a re-fetch.
    """

    head_sha: str = Field(description="PR head commit these inputs were fetched for (the turn key).")
    pr_metadata: PRMetadata = Field(description="The PR's metadata (title/body/branches/labels/…).")
    pr_comments: list[PRComment] = Field(default_factory=list, description="The PR's reviewable inline comments.")
    pr_files: list[PRFile] = Field(default_factory=list, description="The PR's reviewable files with code context.")


# Reused leaf models back the work-log entry types; ReviewHog adds findings + verdicts. The
# working-state types (chunk_set / perspective_result) are per-turn pipeline scaffolding the
# DB-driven resume reads back — head_sha-scoped, latest-wins within a turn.
ReviewLogArtefactContent = TaskRunArtefact | Commit | CodeReference | NoteArtefact
ReviewWorkingStateContent = (
    ChunkSetArtefact | PerspectiveSelectionArtefact | PerspectiveResultArtefact | PRSnapshotArtefact
)
ReviewArtefactContent = ReviewIssueFinding | ValidationVerdict | ReviewLogArtefactContent | ReviewWorkingStateContent

# Keys must match `ReviewReportArtefact.ArtefactType` values exactly (asserted by a test).
ARTEFACT_CONTENT_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "issue_finding": ReviewIssueFinding,
    "validation_verdict": ValidationVerdict,
    "task_run": TaskRunArtefact,
    "commit": Commit,
    "code_reference": CodeReference,
    "note": NoteArtefact,
    "chunk_set": ChunkSetArtefact,
    "perspective_selection": PerspectiveSelectionArtefact,
    "perspective_result": PerspectiveResultArtefact,
    "pr_snapshot": PRSnapshotArtefact,
}
_ARTEFACT_TYPE_BY_MODEL: Mapping[type[BaseModel], str] = {model: t for t, model in ARTEFACT_CONTENT_SCHEMAS.items()}


def artefact_type_for(content: BaseModel) -> str:
    """The artefact type a content model persists as (exact class match).

    Deriving the row's type from the model class makes a type/content mismatch unrepresentable.
    """
    artefact_type = _ARTEFACT_TYPE_BY_MODEL.get(type(content))
    if artefact_type is None:
        raise ArtefactContentValidationError(f"{type(content).__name__} is not a review artefact content model")
    return artefact_type


def parse_artefact_content(artefact_type: str, content: str | dict | list) -> ReviewArtefactContent:
    """Parse a raw payload (JSON text or deserialized JSON) into `artefact_type`'s content model.

    The read/write boundary: raises `ArtefactContentValidationError` on an unknown type, malformed
    JSON, or schema mismatch.
    """
    schema = ARTEFACT_CONTENT_SCHEMAS.get(artefact_type)
    if schema is None:
        raise ArtefactContentValidationError(f"Unknown review artefact type {artefact_type!r}")
    try:
        if isinstance(content, str):
            return cast(ReviewArtefactContent, schema.model_validate_json(content))
        return cast(ReviewArtefactContent, schema.model_validate(content))
    except ValidationError as e:
        raise ArtefactContentValidationError(str(e)) from e
