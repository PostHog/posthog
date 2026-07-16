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


# The sandbox model occasionally emits well-formed issues but drops the required `priority` field,
# which fails strict validation and discards the whole chunk. When salvaging, default such issues to
# `should_fix`: the neutral middle tier keeps the finding visible without forcing a merge-block, and
# the downstream validator still investigates each finding and can re-rank it.
_SALVAGE_DEFAULT_PRIORITY = IssuePriority.SHOULD_FIX


def salvage_issues_review(text: str) -> IssuesReview:
    """Best-effort recovery of a chunk-review end-turn that failed strict validation.

    Targets the nondeterministic LLM slip where issues are otherwise well-formed but omit (or
    misspell) the required `priority`. Fills a sane default for any issue missing a valid priority so
    one dropped field doesn't discard the whole chunk, then validates as normal. Raises if the text
    isn't recoverable JSON at all — the caller then fails the run as it did before.
    """
    # Lazy import keeps the heavy tasks facade off this widely-imported model module's import path.
    from products.tasks.backend.facade.agents import extract_json_from_text  # noqa: PLC0415

    data = extract_json_from_text(text=text, label="chunk review salvage")
    if isinstance(data, dict):
        issues = data.get("issues")
        if isinstance(issues, list):
            valid_priorities = {priority.value for priority in IssuePriority}
            for issue in issues:
                if isinstance(issue, dict) and issue.get("priority") not in valid_priorities:
                    issue["priority"] = _SALVAGE_DEFAULT_PRIORITY.value
    return IssuesReview.model_validate(data)


class PerspectiveType(Enum):
    """Enum for the review perspectives, each run independently and in parallel per chunk."""

    LOGIC_CORRECTNESS = "Logic & Correctness"
    CONTRACTS_SECURITY = "Contracts & Security"
    PERFORMANCE_RELIABILITY = "Performance & Reliability"
