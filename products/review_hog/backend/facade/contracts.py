"""What PostHog Review hands to other products and to its own views. No Django here."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen

from products.review_hog.backend.facade.enums import (
    AutomaticFlashFor,
    AutomaticReviewReason,
    DefaultReviewMode,
    PreferenceSource,
    PRReviewRequestStatus,
    RepositoryOwnerKind,
    ResolveSkipReason,
    ReviewInstallationClaimScope,
    ReviewProjectSettingsBotPullRequests,
    ReviewRepositoryPersonKind,
    ReviewRequestRefusal,
    ReviewUserRepositoryChoiceMode,
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


class InvalidPreference(ValueError):
    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


class Unset:
    """Marks a field the request did not mention, because None is a valid value."""


UNSET = Unset()


class RepositorySettingsError(Exception):
    """A write the rules do not allow. The API answers 400 with the message."""


class GitHubRepositoryListError(Exception):
    """GitHub did not return the repository list of an installation. The API answers 502."""


class RepositoryNotFoundError(LookupError):
    """The project has no settings for the repository."""


class PersonNotActiveMemberError(Exception):
    """The user to add to a people list is not an active member of the project's organization."""


@frozen
class ProjectRef:
    """Another project, named only inside its own organization."""

    team_id: int
    name: str | None

    @property
    def label(self) -> str:
        return f"the {self.name} project" if self.name else "a project in another organization"


class OwnershipConflict(Exception):
    """Another project already holds what this write asks for. The API answers 409."""

    def __init__(self, message: str, project: ProjectRef | None) -> None:
        super().__init__(message)
        self.project = project


@frozen
class AutomaticReviewDecision:
    flash: bool
    reason: AutomaticReviewReason


@frozen
class ReviewUserRef:
    """The fields of a user that the core `UserBasicSerializer` reads."""

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: Mapping[str, object] | None
    role_at_organization: str | None


@frozen
class ReviewRepositoryPersonEntry:
    """A person on one of the two lists of the project rule or of a repository exception."""

    id: UUID
    user: ReviewUserRef
    kind: ReviewRepositoryPersonKind


@frozen
class ReviewRepositorySettings:
    """A repository this project has settings for, with the people on its exception's lists."""

    id: UUID
    installation_id: str
    github_repo_id: int | None
    full_name: str
    selected: bool
    flash_for: AutomaticFlashFor | None
    people: Sequence[ReviewRepositoryPersonEntry]
    created_by: ReviewUserRef | None
    created_at: datetime


@frozen
class ReviewRepositoryWriteOutcome:
    # None when the write left nothing to store, so the row was deleted.
    repository: ReviewRepositorySettings | None
    # The project that took all repositories of the installation, when this write took one from it.
    taken_from: ProjectRef | None


@frozen
class ReviewInstallationClaimInfo:
    id: UUID
    installation_id: str
    scope: ReviewInstallationClaimScope
    account_name: str
    created_by: ReviewUserRef | None
    created_at: datetime


@frozen
class ReviewInstallationInfo:
    """A GitHub installation connected to the project, and which of its repositories the project reviews."""

    installation_id: str
    account_name: str
    connected_by: ReviewUserRef | None
    claim_id: UUID | None
    scope: ReviewInstallationClaimScope | None
    all_taken_by: ProjectRef | None


@frozen
class ReviewRepositoryChoiceInfo:
    """A user's own automatic review choice for their pull requests in one repository."""

    id: UUID
    installation_id: str
    github_repo_id: int | None
    full_name: str
    mode: ReviewUserRepositoryChoiceMode


@frozen
class ReviewRepositoryChoiceOutcome:
    # None when the value equals the inherited one, so no choice is stored.
    choice: ReviewRepositoryChoiceInfo | None
    my_result: AutomaticReviewDecision


@frozen
class ReviewProjectSettingsInfo:
    """The project rule, its Full review defaults, its people lists, and the connected installations."""

    flash_for: AutomaticFlashFor
    bot_prs: ReviewProjectSettingsBotPullRequests
    urgency_threshold: UrgencyThreshold
    celebrate_clean_reviews: bool
    people: Sequence[ReviewRepositoryPersonEntry]
    installations: Sequence[ReviewInstallationInfo]


@frozen
class ReviewRepositoryException:
    flash_for: AutomaticFlashFor
    people: Sequence[ReviewRepositoryPersonEntry]


@frozen
class ReviewRepositoryOverviewEntry:
    """One repository of an installation, joined with this project's settings and the viewer's."""

    full_name: str
    github_repo_id: int | None
    owner: RepositoryOwnerKind
    owner_project: ProjectRef | None
    in_project: bool
    selected: bool
    repository_id: UUID | None
    exception: ReviewRepositoryException | None
    my_choice: ReviewUserRepositoryChoiceMode | None
    my_choice_id: UUID | None
    my_result: AutomaticReviewDecision
    inherited_result: AutomaticReviewDecision
    repository_result: AutomaticReviewDecision


@frozen
class ReviewRepositoryOverviewPage:
    installation_id: str
    claim_scope: ReviewInstallationClaimScope | None
    entries: Sequence[ReviewRepositoryOverviewEntry]
    # Entries that match the search and the view, on every page.
    total: int
    my_choices_unlike_default: int
