"""Choices the review contracts carry. No Django here, so clients and other products can read them."""

from enum import StrEnum

from posthog.enums import LabeledStrEnum


class PRReviewRequestStatus(StrEnum):
    STARTED = "started"
    JOINED_RUNNING_REVIEW = "joined_running_review"
    ALREADY_REVIEWED = "already_reviewed"
    # The request cannot start a run as asked: the repository, the pull request or its state.
    INVALID = "invalid"
    # The requested mode is not available in this project.
    NOT_ALLOWED = "not_allowed"
    # The pull request's review cycle is busy, so the request is refused rather than queued.
    BUSY = "busy"
    # A review rule refuses the request for this pull request; `refusal` says which.
    REFUSED = "refused"


class ResolveSkipReason(LabeledStrEnum):
    """Why an accepted request runs no resolution stage."""

    RUN_MODE_EXCLUDES_RESOLVE = "run_mode_excludes_resolve", "The run mode never resolves comments"
    OWNER_NOT_OPTED_IN = "owner_not_opted_in", "The pull request owner has not opted in to resolution"
    ALREADY_REVIEWED = "already_reviewed", "No run starts, because the head already has a review in this mode"


class ReviewRequestRefusal(LabeledStrEnum):
    """Why a request is refused. Clients show a reason per code."""

    FLASH_AFTER_FULL = "flash_after_full", "Standard after a published Deep review"
    RESOLUTION_NOT_OPTED_IN = "resolution_not_opted_in", "The pull request owner has not opted in to resolution"


class DefaultReviewMode(LabeledStrEnum):
    FOLLOW = "follow", "Let each repository decide"
    FLASH = "flash", "On everywhere"
    OFF = "off", "Off everywhere"


class UrgencyThreshold(LabeledStrEnum):
    # Values mirror `IssuePriority`, so the threshold compares directly against finding priorities.
    CONSIDER = "consider", "Consider (all)"
    SHOULD_FIX = "should_fix", "Should fix"
    MUST_FIX = "must_fix", "Must fix"


class PreferenceSource(LabeledStrEnum):
    USER = "user", "Set by the user"
    PROJECT = "project", "Project default"
    DEFAULT = "default", "Built-in default"


class ReviewSkillKind(StrEnum):
    """The review skill families a user configures. Each family is one skill-name prefix."""

    # Multi-enable: several run on one review, and at least one must stay enabled.
    PERSPECTIVE = "perspective"
    # Single-active: exactly one runs, and selecting one switches the others off.
    VALIDATION = "validation"
    BLIND_SPOTS = "blind_spots"
    RESOLUTION = "resolution"
