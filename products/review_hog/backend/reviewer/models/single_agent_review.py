import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from products.review_hog.backend.reviewer.models.issues_review import ReportedPriority


class SingleAgentFinding(BaseModel):
    """One finding of the single-agent Flash review, in the shape the reviewer writes it."""

    title: str = Field(description="At most 80 characters, imperative, without a [P#] tag.")
    priority: ReportedPriority = Field(
        description=(
            "P0: drop everything to fix, blocks release or major usage. P1: urgent, fix in the next cycle."
            " P2: normal, fix eventually. P3: low, nice to have."
        )
    )
    file: str = Field(description="File path relative to the repository root.")
    line_start: int = Field(description="First line of the finding in the file at the PR's head commit.")
    line_end: int | None = Field(
        default=None, description="Last line of the finding at the head commit. Null for a single line."
    )
    body: str = Field(
        description=(
            "One paragraph of about 300-400 characters: the trigger (the input, state, or environment the"
            " problem needs), the consequence, and the anchor (the function, call site, or invariant involved)."
            " End with at most one short clause on the fix direction."
        )
    )
    suggestion_code: str | None = Field(
        default=None,
        description=(
            "Only when the fix is a small replacement you are certain of: the exact new code for line_start"
            " to line_end, with the original indentation. Null otherwise."
        ),
    )

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: object) -> object:
        """Accept 1, "1", "P1" or "[P1]" and store "P1"; anything else fails validation as given."""
        match = re.fullmatch(r"\s*\[?P?([0-3])\]?\s*", str(value), re.IGNORECASE)
        return f"P{match.group(1)}" if match else value


class SingleAgentReview(BaseModel):
    """The single-agent Flash review's whole answer for one PR."""

    findings: list[SingleAgentFinding] = Field(
        default_factory=list, description="Every qualifying finding. Empty when nothing qualifies."
    )
    overall_correctness: Literal["patch is correct", "patch is incorrect"] | None = Field(
        default=None, description="Whether the patch is free of bugs and other blocking issues."
    )
    overall_explanation: str | None = Field(
        default=None, description="One to three sentences that justify overall_correctness."
    )
