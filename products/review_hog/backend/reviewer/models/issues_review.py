import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from posthog.dataclasses import frozen

logger = logging.getLogger(__name__)


# Issue priority enum
class IssuePriority(Enum):
    """Priority levels for code review issues."""

    MUST_FIX = "must_fix"  # Critical issues that should block merge
    SHOULD_FIX = "should_fix"  # Significant improvements needed
    CONSIDER = "consider"  # Nice-to-have improvements


# The single-agent reviewer's own scale. Storage folds P0 and P1 into `IssuePriority.MUST_FIX`.
ReportedPriority = Literal["P0", "P1", "P2", "P3"]


class LineRange(BaseModel):
    """Line range in format 'X-Y'"""

    start: int = Field(description="Issue's-related code start line")
    end: int | None = Field(
        description="Issue's-related code end line. None if a single line issue",
        default=None,
    )


# Chunk review models
class Issue(BaseModel):
    """Represents a code review issue."""

    id: str = Field(
        description=(
            "Unique issue ID in format '{pass_number}-{chunk_id}-{issue_number}' where pass_number is"
            " from the current pass, chunk_id is from the current chunk, and issue_number is sequential"
            " (1, 2, 3...) within the chunk"
        )
    )
    title: str = Field(description="Issue title")
    file: str = Field(description="Path to the file containing the issue")
    lines: list[LineRange] = Field(description="Line range in format 'X-Y'")
    issue: str = Field(description="Description of the problem")
    suggestion: str = Field(description="Specific fix or improvement")
    priority: IssuePriority = Field(description="Priority level of the issue")
    is_directly_related_to_changes: bool = Field(
        description=(
            "Whether the issue is directly caused by the changes in the PR or was noticed just because of the same file"
        ),
        default=False,
    )
    source_perspective: str | None = Field(
        description="Which review perspective produced this issue; set by the pipeline, not the model",
        default=None,
    )
    # Only the single-agent design writes this, from its own output schema. It is left out of this
    # model's JSON schema so the pipeline's review prompts never ask for it, and an unset value is
    # left out of dumps so the issue JSON the pipeline sends to dedup and validation stays the same.
    suggestion_code: SkipJsonSchema[str | None] = Field(
        description="Replacement code for the finding's line range, posted as a GitHub suggestion",
        default=None,
        exclude_if=lambda value: value is None,
    )
    # Single-agent only, like `suggestion_code`: the reviewer's P0-P3, so P0 and P1 stay apart after
    # `priority` folds them into one level.
    reported_priority: SkipJsonSchema[ReportedPriority | None] = Field(
        description="The reviewer's own P0-P3 priority",
        default=None,
        exclude_if=lambda value: value is None,
    )


# Why a single-agent turn drops a finding. A `dedup_*` drop repeats an earlier turn's finding, a PR
# comment, a main finding (anchor), or a finding of its own session or lens (sibling); `dedup_unmatched`
# means the dedup named nothing it was shown. `cap` is the cut in `compose_flash_findings`.
DropDisposition = Literal[
    "dedup_prior",
    "dedup_comment",
    "dedup_anchor",
    "dedup_sibling",
    "dedup_unmatched",
    "cap",
]


@frozen
class DroppedIssue:
    """A finding a single-agent turn does not keep, and why."""

    issue: Issue
    disposition: DropDisposition
    # What a dedup drop repeats: a finding of this turn, or the issue key of an earlier turn's finding,
    # or `comment:<id>`.
    duplicate_of: Issue | str | None = None
    # The 1-based position in the turn's ranked findings, for a finding the cap cut.
    rank: int | None = None
    # The dedup LLM call failed, so the positional pre-filter alone decided this drop.
    dedup_fallback: bool = False


class IssuesReview(BaseModel):
    """Complete review of the chunk issues."""

    issues: list[Issue] = Field(default_factory=list, description="List of issues found in the chunk")


class PerspectiveType(Enum):
    """Enum for the review perspectives, each run independently and in parallel per chunk."""

    LOGIC_CORRECTNESS = "Logic & Correctness"
    CONTRACTS_SECURITY = "Contracts & Security"
    PERFORMANCE_RELIABILITY = "Performance & Reliability"
