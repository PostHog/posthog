import logging
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Issue priority enum
class IssuePriority(Enum):
    """Priority levels for code review issues."""

    MUST_FIX = "must_fix"  # Critical issues that should block merge
    SHOULD_FIX = "should_fix"  # Significant improvements needed
    CONSIDER = "consider"  # Nice-to-have improvements


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


class IssuesReview(BaseModel):
    """Complete review of the chunk issues."""

    issues: list[Issue] = Field(default_factory=list, description="List of issues found in the chunk")


class PerspectiveType(Enum):
    """Enum for the review perspectives, each run independently and in parallel per chunk."""

    LOGIC_CORRECTNESS = "Logic & Correctness"
    CONTRACTS_SECURITY = "Contracts & Security"
    PERFORMANCE_RELIABILITY = "Performance & Reliability"
