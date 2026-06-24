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

from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
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

    `issue_key` is the finding's stable identity across review turns — the latest row per key is
    the current state — so a re-review marks a finding still-open / resolved / newly-appeared
    instead of duplicating it.
    """

    issue_key: str = Field(description="Stable identity across turns (e.g. file + anchor + lens).")
    title: str = Field(description="Issue title.")
    file: str = Field(description="Repository-relative path to the file containing the issue.")
    lines: list[LineRange] = Field(default_factory=list, description="Affected line ranges.")
    body: str = Field(description="Description of the problem.")
    suggestion: str = Field(description="Specific fix or improvement.")
    priority: IssuePriority = Field(description="Priority level of the finding.")
    source_lens: str | None = Field(default=None, description="Which review lens produced this finding.")
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

    @field_validator("issue_key", "argumentation")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


# Reused leaf models back the work-log entry types; ReviewHog adds findings + verdicts.
ReviewLogArtefactContent = TaskRunArtefact | Commit | CodeReference | NoteArtefact
ReviewArtefactContent = ReviewIssueFinding | ValidationVerdict | ReviewLogArtefactContent

# Keys must match `ReviewReportArtefact.ArtefactType` values exactly (asserted by a test).
ARTEFACT_CONTENT_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "issue_finding": ReviewIssueFinding,
    "validation_verdict": ValidationVerdict,
    "task_run": TaskRunArtefact,
    "commit": Commit,
    "code_reference": CodeReference,
    "note": NoteArtefact,
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
