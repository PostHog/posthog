"""What PostHog Review hands to other products and to its own views. No Django here."""

from collections.abc import Mapping

from posthog.dataclasses import frozen

from products.review_hog.backend.facade.enums import (
    DefaultReviewMode,
    PreferenceSource,
    PRReviewRequestStatus,
    ResolveSkipReason,
    ReviewRequestRefusal,
    UrgencyThreshold,
)

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


class ReviewSkillNameError(ValueError):
    """The skill name does not carry the prefix of the requested review skill kind."""


class ReviewSkillNotFoundError(LookupError):
    """No live review skill with this name is visible to the user on the project."""


class LastEnabledPerspectiveError(ValueError):
    """The change would leave the user with no enabled review perspective."""


@frozen
class ReviewSkill:
    """A live review skill the user can see, without the user's state for it."""

    skill_name: str
    description: str
    body: str


@frozen
class ReviewSkillChoice:
    """One review skill in a user's config menu, with the user's state for it.

    `enabled` is "runs on the user's reviews": enabled for a perspective, active for a single-active kind.
    """

    skill_name: str
    enabled: bool
    description: str
    body: str


@frozen
class ReviewProjectPreferenceDefaults:
    urgency_threshold: UrgencyThreshold
    celebrate_clean_reviews: bool


@frozen
class ReviewUserPreferences:
    """A user's effective review preferences, where each value comes from, and the project defaults."""

    default_review_mode: DefaultReviewMode
    review_drafts: bool
    resolve_comments: bool
    urgency_threshold: UrgencyThreshold
    celebrate_clean_reviews: bool
    review_inbox_prs: bool
    stamphog_review_inbox_prs: bool
    sources: Mapping[str, PreferenceSource]
    project_defaults: ReviewProjectPreferenceDefaults
    stamphog_connected: bool
