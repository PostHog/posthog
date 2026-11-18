"""Types of the head review status that review_hog exposes to other products. No Django imports."""

from dataclasses import dataclass
from enum import StrEnum


class HeadReviewState(StrEnum):
    # Accepted but not started, or running. A turn stays pending until its findings are on the PR.
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class HeadReviewStatus:
    """Where PostHog Review's review of one pull request head stands."""

    state: HeadReviewState
    # "Standard" or "Deep" for a completed turn. Empty while pending or failed.
    review_kind: str
    # Valid findings of a completed turn. Zero while pending or failed.
    findings_count: int
    # True when the turn posted a review on the PR. A clean turn posts nothing, so it stays False.
    published: bool
    head_sha: str
    # The base branch the completed turn reviewed the head against. Empty when it is not known.
    base_branch: str = ""
    # The merge base the completed turn took the diff against. Empty when it is not known.
    base_sha: str = ""
    # The changed files the completed turn left out of the review, for example lock files or a chunk no unit read.
    skipped_paths: tuple[str, ...] = ()
