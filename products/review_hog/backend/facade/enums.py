"""Choices the review contracts carry. No Django here, so clients and other products can read them."""

from enum import Enum, StrEnum

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


class AutomaticFlashFor(LabeledStrEnum):
    """Who gets automatic Flash reviews under a project rule or a repository exception."""

    EVERYONE = "everyone", "Automatic Flash for everyone"
    LISTED = "listed", "Automatic Flash for these people"
    OFF = "off", "Automatic Flash opt-in only"


class ReviewProjectSettingsBotPullRequests(LabeledStrEnum):
    SKIP = "skip", "Not reviewed"
    RUN = "run", "Automatic Flash"


class ReviewInstallationClaimScope(LabeledStrEnum):
    ALL = "all", "All repositories"
    SELECTED = "selected", "Only selected repositories"


class ReviewRepositoryPersonKind(LabeledStrEnum):
    LISTED = "listed", "Listed"
    EXCEPTED = "excepted", "Excepted"


class ReviewUserRepositoryChoiceMode(LabeledStrEnum):
    FLASH = "flash", "Flash"
    OFF = "off", "Off"


class AutomaticReviewReason(LabeledStrEnum):
    OWN_REPOSITORY_CHOICE = "own_repository_choice", "Own choice for this repository"
    OWN_DEFAULT = "own_default", "Own default"
    REPOSITORY_EVERYONE = "repository_everyone", "The repository exception reviews everyone"
    REPOSITORY_EXCEPTED = "repository_excepted", "Excepted by the repository exception"
    REPOSITORY_LISTED = "repository_listed", "Listed by the repository exception"
    REPOSITORY_NOT_LISTED = "repository_not_listed", "Not listed by the repository exception"
    REPOSITORY_OPT_IN = "repository_opt_in", "The repository exception reviews only people who opt in"
    PROJECT_EVERYONE = "project_everyone", "The project reviews everyone"
    PROJECT_EXCEPTED = "project_excepted", "Excepted by the project"
    PROJECT_LISTED = "project_listed", "Listed by the project"
    PROJECT_NOT_LISTED = "project_not_listed", "Not listed by the project"
    PROJECT_OPT_IN = "project_opt_in", "The project reviews only people who opt in"
    BOT_REVIEWED = "bot_reviewed", "The project reviews bot pull requests"
    BOT_SKIPPED = "bot_skipped", "The project does not review bot pull requests"
    NOT_IN_PROJECT = "not_in_project", "This project does not review the repository"


class RepositoryOwnerKind(LabeledStrEnum):
    THIS_PROJECT = "this_project", "This project"
    OTHER_PROJECT = "other_project", "Another project"
    NONE = "none", "No project"


class RepositoryOverviewView(LabeledStrEnum):
    ALL = "all", "All repositories"
    IN_PROJECT = "in_project", "In this project"
    EXCEPTIONS = "exceptions", "With exceptions"
    MINE = "mine", "My choices"
    DIFFERS = "differs", "Different from the project"


class IssuePriority(Enum):
    """Priority levels for code review issues."""

    MUST_FIX = "must_fix"  # Critical issues that should block merge
    SHOULD_FIX = "should_fix"  # Significant improvements needed
    CONSIDER = "consider"  # Nice-to-have improvements


class ReviewReportScope(StrEnum):
    """Whose reviews a read covers."""

    MINE = "mine"
    EVERYONE = "everyone"
    # The user's own last Deep reviews. Only the perspective stats read this scope.
    OWN_DEEP = "own_deep"


class ReviewActivityFilter(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"


class ReviewPRState(LabeledStrEnum):
    NOT_REVIEWED = "not_reviewed", "Not reviewed"
    QUEUED = "queued", "Queued"
    REVIEWING = "reviewing", "Reviewing"
    RESOLVING = "resolving", "Resolving"
    IDLE = "idle", "Idle"
    UNKNOWN = "unknown", "Unknown"


class ReviewRequestOutcomeStatus(LabeledStrEnum):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    SKIPPED = "skipped", "Skipped"
    FAILED = "failed", "Failed"
    UNKNOWN = "unknown", "Unknown"
