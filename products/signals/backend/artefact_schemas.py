"""Pydantic content schemas for `SignalReportArtefact` rows.

Each `SignalReportArtefact` stores its typed payload as JSON text in `content`. This module is
the canonical home of every artefact content shape: one model per artefact type. Raw payloads
are parsed into these models once, at the boundaries — `parse_artefact_content` for API writes
and for reads that consume stored rows — and everything in between passes the typed model
around; the model helpers derive a row's type from the content model's class. The module is
kept deliberately dependency-light (pydantic only) so models, views, and temporal code can all
import it without pulling in the report-research / sandbox machinery.

Reads of legacy rows that predate these schemas stay tolerant (parse failures are skipped or
degraded, never raised to users).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel, Field, RootModel, ValidationError, field_validator, model_validator

# Product / type identifier parts must be routing-safe — mirrors the custom-agent identifier
# contract (see custom_agent.schemas.validate_identifier_part), kept inline so this module stays
# dependency-light (pydantic only).
_IDENTIFIER_PART_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ArtefactContentValidationError(ValueError):
    """Raised when artefact content does not match the schema registered for its type."""


# ── Status artefact schemas ──────────────────────────────────────────────────────
#
# Status artefacts describe the report's current state (judgments, repo selection, suggested
# reviewers); append-only, latest row of each type wins. The judgment models double as LLM
# output schemas in `report_generation/research.py` — their field descriptions are prompt
# material, not just docs.


class ActionabilityChoice(str, Enum):
    IMMEDIATELY_ACTIONABLE = "immediately_actionable"
    REQUIRES_HUMAN_INPUT = "requires_human_input"
    NOT_ACTIONABLE = "not_actionable"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class SignalFinding(BaseModel):
    """Content schema for a `signal_finding` artefact: one investigation result per signal."""

    signal_id: str = Field(description="The signal_id from the input signal list")
    relevant_code_paths: list[str] = Field(
        description=(
            "File paths in the codebase relevant to this signal, ordered from most critical first. "
            "The first path should be the highest-impact file (e.g. the buggy module or core feature file). "
            "Then include supporting paths."
        ),
    )
    relevant_commit_hashes: dict[str, str] = Field(
        default_factory=dict,
        json_schema_extra={"minProperties": 1},
        description=(
            "A mapping of 'git commit short SHA (7 characters)' -> 'reason'. "
            "Values are short explanations of WHY each commit is relevant. "
            "Use `git blame` on the most critical code paths to identify commits that caused, or are most closely related to, "
            "the issue described by this report. Prioritize causative commits "
            "(e.g. the commit that introduced a bug) over general authorship commits. Include 1-5 commits."
        ),
    )
    data_queried: str = Field(
        description=(
            "What PostHog MCP queries you ran (e.g. execute-sql, query-run, insight-query) "
            "and what the results showed. If no relevant queries could be run, explain why."
        ),
    )
    verified: bool = Field(
        description=(
            "Whether you could confirm the signal's claim by finding supporting evidence "
            "in code or data. False if the claim couldn't be verified either way."
        ),
    )


class ActionabilityAssessment(BaseModel):
    """Content schema for an `actionability_judgment` artefact."""

    explanation: str = Field(
        description=(
            "2-3 sentence evidence-grounded explanation of your actionability assessment. "
            "Reference specific code paths and data points from your research."
        ),
    )
    actionability: ActionabilityChoice = Field(
        description="Overall actionability assessment. Must be one of the allowed enum values — do not invent new ones.",
    )
    already_addressed: bool = Field(
        description=(
            "Whether the core issue described by this report appears to have been "
            "already fixed or addressed in recent code changes. Tracked separately from `actionability`."
        ),
    )

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Explanation must not be empty")
        return v


class PriorityAssessment(BaseModel):
    """Content schema for a `priority_judgment` artefact."""

    explanation: str = Field(
        description=(
            "2-3 sentence justification for the priority level. "
            "Reference quantified user impact, error frequency, or scope of affected code paths."
        ),
    )
    priority: Priority = Field(description="Priority (P0-P4)")
    dollar_value: float | None = Field(
        default=None,
        description=(
            "Peak estimate (USD) of the real dollar value of merging the fix/change this report leads to. "
            "Reason internally about a plausible value range first; set this to the most likely point "
            "within that range (the peak of your belief distribution). Should align with the assigned "
            "priority. Nullable for backward compatibility only — prefer a best-effort peak over null."
        ),
    )

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Explanation must not be empty")
        return v


class SafetyJudgment(BaseModel):
    """Content schema for a `safety_judgment` artefact: the prompt-injection safety verdict."""

    choice: bool = Field(description="True when the report's signals are judged safe to act on.")
    explanation: str | None = Field(
        default=None, description="Why the report was judged unsafe; null/omitted when safe."
    )


class RepoSelection(BaseModel):
    """Content schema for a `repo_selection` artefact.

    Signals-owned mirror of `products.tasks.backend.repo_selection.RepoSelectionResult` (this
    module must stay free of cross-product imports); a parity test guards against field drift.
    """

    repository: str | None = Field(
        description="Selected repository in 'owner/repo' format, or null if none of the candidates are relevant."
    )
    reason: str = Field(description="Why this repository was selected (or why none matched).")
    task_id: str | None = Field(
        default=None,
        description="UUID of the sandbox task that performed the selection, when an agent ran (null for "
        "the 0/1-candidate shortcuts that never spawn a sandbox).",
    )


class SuggestedReviewerEntry(BaseModel):
    """One reviewer in a `suggested_reviewers` artefact's content list."""

    github_login: str = Field(description="GitHub login identifying the reviewer (stored lowercased).")
    github_name: str | None = Field(default=None, description="Optional human-readable display name.")
    relevant_commits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Commit evidence explaining why this reviewer is relevant.",
    )

    @field_validator("github_login")
    @classmethod
    def github_login_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class SuggestedReviewers(RootModel[list[SuggestedReviewerEntry]]):
    """Content schema for a `suggested_reviewers` artefact — the content root is a JSON list."""


class Dismissal(BaseModel):
    """Content schema for a `dismissal` artefact: feedback captured when a report is dismissed/snoozed.

    The user fields predate row-level attribution and are kept for compatibility with existing
    rows and readers; new rows also carry attribution on the artefact row itself.
    """

    reason: str | None = Field(default=None, description="Caller-owned dismissal reason code.")
    note: str | None = Field(default=None, description="Free-form dismissal note.")
    user_id: int | None = Field(default=None, description="ID of the dismissing user, when known.")
    user_uuid: str | None = Field(default=None, description="UUID of the dismissing user, when known.")
    slack_user_id: str | None = Field(
        default=None, description="Slack user who dismissed via a Slack action, when that's where the click came from."
    )


class VideoSegment(RootModel[dict[str, Any] | list[Any]]):
    """Content schema for a `video_segment` artefact.

    Deliberately permissive: the type predates this registry and has no in-repo production
    writer, so any JSON object/array validates rather than guessing at a shape.
    """


# ── Log artefact schemas ─────────────────────────────────────────────────────────
#
# Log artefacts record discrete work done on a report; they accumulate and are addressable by id.


# Bounds for referenced source text: references are pointers with a small excerpt, not a vehicle
# for shipping file contents into the report log.
_MAX_CODE_LINE_LENGTH = 1000
_MAX_CODE_REFERENCE_LINES = 20


class CodeReference(BaseModel):
    """Content schema for a `code_reference` artefact: a contiguous span of source lines."""

    file_path: str = Field(description="Repository-relative path to the referenced file.")
    start_line: int = Field(ge=1, description="First line of the referenced range (1-indexed, inclusive).")
    end_line: int = Field(ge=1, description="Last line of the referenced range (1-indexed, inclusive).")
    contents: str = Field(
        description=f"The exact source text of lines start_line through end_line. At most "
        f"{_MAX_CODE_REFERENCE_LINES} lines of at most {_MAX_CODE_LINE_LENGTH} characters each."
    )
    relevance_note: str = Field(
        description="Short note on why this code is relevant to the report.",
    )

    @field_validator("file_path", "contents", "relevance_note")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @field_validator("contents")
    @classmethod
    def contents_must_be_bounded(cls, v: str) -> str:
        lines = v.split("\n")
        if len(lines) > _MAX_CODE_REFERENCE_LINES:
            raise ValueError(f"must not exceed {_MAX_CODE_REFERENCE_LINES} lines")
        if any(len(line) > _MAX_CODE_LINE_LENGTH for line in lines):
            raise ValueError(f"lines must not exceed {_MAX_CODE_LINE_LENGTH} characters")
        return v

    @model_validator(mode="after")
    def line_span_must_be_valid(self) -> CodeReference:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        if self.end_line - self.start_line + 1 > _MAX_CODE_REFERENCE_LINES:
            raise ValueError(f"the referenced range must not exceed {_MAX_CODE_REFERENCE_LINES} lines")
        return self


class LineReference(BaseModel):
    """Content schema for a `line_reference` artefact: a single source line callout (a point).

    Used for tour-style features or to let an agent point at one specific line of behaviour,
    as opposed to `code_reference` which spans a contiguous range.
    """

    file_path: str = Field(description="Repository-relative path to the referenced file.")
    line: int = Field(ge=1, description="The referenced line number (1-indexed).")
    note: str = Field(description="Short note on what this line shows or why it matters.")
    contents: str | None = Field(
        default=None,
        max_length=_MAX_CODE_LINE_LENGTH,
        description=f"The exact source text of the referenced line, if available "
        f"(at most {_MAX_CODE_LINE_LENGTH} characters).",
    )

    @field_validator("file_path", "note")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v


class Commit(BaseModel):
    """Content schema for a `commit` artefact: one commit pushed in relation to the report.

    Recorded automatically by the agent harness after each successful signed-commit push (one
    artefact per commit), so the report log shows exactly what landed, when, and from which task.
    """

    repository: str = Field(description="GitHub repository the commit was pushed to, as `owner/repo`.")
    branch: str = Field(description="Branch the commit was pushed to.")
    commit_sha: str = Field(description="Full or abbreviated SHA of the pushed commit.")
    message: str = Field(description="The commit message headline.")
    note: str | None = Field(default=None, description="Optional short note on what this commit does.")

    @field_validator("repository", "branch", "commit_sha", "message")
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


# ── Type mapping ─────────────────────────────────────────────────────────────────

# Content models that describe the report's current state (latest row of each type wins) vs
# entries that record discrete work (accumulate). `SignalFinding` (keyed by signal_id) and
# `Dismissal` (stacking) have their own semantics; `VideoSegment` is a legacy plain append.
StatusArtefactContent = (
    SafetyJudgment | ActionabilityAssessment | PriorityAssessment | RepoSelection | SuggestedReviewers
)
LogArtefactContent = CodeReference | LineReference | Commit | TaskRunArtefact | NoteArtefact
ArtefactContent = StatusArtefactContent | LogArtefactContent | SignalFinding | Dismissal | VideoSegment

# Keys are `SignalReportArtefact.ArtefactType` values, kept as plain strings so this module stays
# Django-free; a test asserts the key set matches the model enum exactly.
ARTEFACT_CONTENT_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "video_segment": VideoSegment,
    "safety_judgment": SafetyJudgment,
    "actionability_judgment": ActionabilityAssessment,
    "priority_judgment": PriorityAssessment,
    "signal_finding": SignalFinding,
    "repo_selection": RepoSelection,
    "suggested_reviewers": SuggestedReviewers,
    "dismissal": Dismissal,
    "code_reference": CodeReference,
    "line_reference": LineReference,
    "commit": Commit,
    "task_run": TaskRunArtefact,
    "note": NoteArtefact,
}

_ARTEFACT_TYPE_BY_MODEL: Mapping[type[BaseModel], str] = {model: t for t, model in ARTEFACT_CONTENT_SCHEMAS.items()}


def artefact_type_for(content: BaseModel) -> str:
    """The artefact type a content model persists as (exact class match).

    Deriving the row's type from the model class makes a type/content mismatch unrepresentable.
    Raises `ArtefactContentValidationError` for models that aren't artefact content schemas.
    """
    artefact_type = _ARTEFACT_TYPE_BY_MODEL.get(type(content))
    if artefact_type is None:
        raise ArtefactContentValidationError(f"{type(content).__name__} is not an artefact content model")
    return artefact_type


def parse_artefact_content(artefact_type: str, content: str | dict | list) -> ArtefactContent:
    """Parse a raw payload (JSON text or deserialized JSON) into `artefact_type`'s content model.

    The boundary parser: API writes and reads of stored rows come through here once, and
    everything past the boundary passes the typed model around. Raises
    `ArtefactContentValidationError` on an unknown type, malformed JSON, or schema mismatch.
    """
    schema = ARTEFACT_CONTENT_SCHEMAS.get(artefact_type)
    if schema is None:
        raise ArtefactContentValidationError(f"Unknown artefact type {artefact_type!r}")
    try:
        if isinstance(content, str):
            return cast(ArtefactContent, schema.model_validate_json(content))
        return cast(ArtefactContent, schema.model_validate(content))
    except ValidationError as e:
        raise ArtefactContentValidationError(str(e)) from e
