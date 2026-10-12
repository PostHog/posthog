"""What PostHog Review hands to other products and to its own views. No Django here."""

from posthog.dataclasses import frozen

from products.review_hog.backend.facade.enums import PRReviewRequestStatus, ResolveSkipReason, ReviewRequestRefusal

# What the trigger runs. The default 'review' includes the resolution stage when the pull request
# owner's `resolve_comments` setting is on; the others are the split button's explicit variants.
# Flash never resolves comments because it must not write code.
RUN_MODE_REVIEW = "review"
RUN_MODE_REVIEW_ONLY = "review_only"
RUN_MODE_RESOLVE_ONLY = "resolve_only"
RUN_MODE_FLASH = "flash"


@frozen
class PRReviewRequestOutcome:
    status: PRReviewRequestStatus
    workflow_id: str = ""
    # Written for the requester. Built from the repository name, the PR number and fixed text only.
    error: str = ""
    refusal: ReviewRequestRefusal | None = None
    repository: str = ""
    pr_number: int | None = None
    head_sha: str | None = None
    # None for a resolve-only run, which reviews nothing.
    review_mode: str | None = None
    # None until the first run of the pull request creates the report.
    report_id: str | None = None
    resolve_skip_reason: ResolveSkipReason | None = None

    @property
    def started(self) -> bool:
        return self.status in (
            PRReviewRequestStatus.STARTED,
            PRReviewRequestStatus.JOINED_RUNNING_REVIEW,
            PRReviewRequestStatus.ALREADY_REVIEWED,
        )

    @property
    def resolve_will_run(self) -> bool:
        return self.started and self.resolve_skip_reason is None
