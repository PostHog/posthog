"""PostHog Review's data surface for its own views and for other products.

Takes plain values and contracts, returns contracts. Keep heavy imports (Temporal, HogQL) off this
module: they go in their own facade submodule.
"""

import logging
from collections.abc import Mapping, Sequence
from uuid import UUID

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.activity_logging import installation_account_name
from products.review_hog.backend.automatic_review_rules import load_people
from products.review_hog.backend.facade.contracts import (
    UNSET,
    RepositoryNotFoundError,
    ReviewDetail,
    ReviewInstallationClaimInfo,
    ReviewInstallationInfo,
    ReviewPerspectiveStats,
    ReviewProjectPreferenceDefaults,
    ReviewProjectSettingsInfo,
    ReviewRepositoryChoiceInfo,
    ReviewRepositoryChoiceOutcome,
    ReviewRepositoryException,
    ReviewRepositoryOverviewEntry,
    ReviewRepositoryOverviewPage,
    ReviewRepositoryPersonEntry,
    ReviewRepositorySettings,
    ReviewRepositoryWriteOutcome,
    ReviewSkill,
    ReviewSkillChoice,
    ReviewSummaryPage,
    ReviewTablePage,
    ReviewUserPreferences,
    ReviewUserRef,
    Unset,
)
from products.review_hog.backend.facade.enums import (
    AutomaticFlashFor,
    RepositoryOverviewView,
    ReviewActivityFilter,
    ReviewInstallationClaimScope,
    ReviewProjectSettingsBotPullRequests,
    ReviewReportScope,
    ReviewRepositoryPersonKind,
    ReviewSkillKind,
    ReviewUserRepositoryChoiceMode,
)
from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
    ReviewUserSettings,
)
from products.review_hog.backend.ownership import RepositoryRef
from products.review_hog.backend.preferences import ReviewPreferences
from products.review_hog.backend.repository_settings import (
    InstallationSummary,
    OverviewEntry,
    ProjectRepositories,
    RepositoryChoices,
    RepositoryOverview,
)
from products.review_hog.backend.review_listing import ReviewListing
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_authoring
from products.review_hog.backend.skill_configs import ReviewSkillMenu
from products.stamphog.backend.facade.api import has_reviewable_repo_config

logger = logging.getLogger(__name__)

# The folded row names a few of its repositories, so people can tell which ones it holds.
FOLDED_PREVIEW_SIZE = 3


def list_review_skill_choices(team_id: int, user_id: int, kind: ReviewSkillKind) -> list[ReviewSkillChoice]:
    """The review skills of `kind` the user can see, by name, with the user's state for each.

    Seeds the canonical skills and the user's canonical config rows first, so a cold team or user
    sees the defaults.
    """
    return ReviewSkillMenu(team_id, user_id, kind).choices()


def get_review_skill(team_id: int, user_id: int, kind: ReviewSkillKind, skill_name: str) -> ReviewSkill:
    """The live review skill of `kind` called `skill_name`, when the user can see it.

    Raises `ReviewSkillNameError` when the name does not carry the prefix of `kind`, and
    `ReviewSkillNotFoundError` when no such skill is visible to the user.
    """
    return ReviewSkillMenu(team_id, user_id, kind).get(skill_name)


def set_review_perspective_enabled(
    team_id: int, user_id: int, perspective: ReviewSkill, enabled: bool
) -> ReviewSkillChoice:
    """Enable or disable one perspective for the user.

    Raises `LastEnabledPerspectiveError` when the user would have no enabled perspective left.
    """
    return ReviewSkillMenu(team_id, user_id, ReviewSkillKind.PERSPECTIVE).set_enabled(perspective, enabled)


def select_review_skill(team_id: int, user_id: int, kind: ReviewSkillKind, skill: ReviewSkill) -> ReviewSkillChoice:
    """Make `skill` the user's single active skill of a single-active `kind`."""
    return ReviewSkillMenu(team_id, user_id, kind).select(skill)


def _stamphog_connected(team_id: int) -> bool:
    # This reads the stamphog product DB, which can fail fast on its own circuit breaker. An
    # informational UI flag must not fail the settings endpoint, so fall back to False.
    try:
        return has_reviewable_repo_config(team_id)
    except Exception:
        logger.exception("review_hog_stamphog_connected_check_failed")
        return False


def _user_preferences(team_id: int, preferences: ReviewPreferences) -> ReviewUserPreferences:
    return ReviewUserPreferences(
        default_review_mode=preferences.default_review_mode,
        review_drafts=preferences.review_drafts,
        resolve_comments=preferences.resolve_comments,
        urgency_threshold=preferences.urgency_threshold,
        celebrate_clean_reviews=preferences.celebrate_clean_reviews,
        review_inbox_prs=preferences.review_inbox_prs,
        stamphog_review_inbox_prs=preferences.stamphog_review_inbox_prs,
        sources=preferences.sources,
        project_defaults=ReviewProjectPreferenceDefaults(
            urgency_threshold=preferences.project.urgency_threshold,
            celebrate_clean_reviews=preferences.project.celebrate_clean_reviews,
        ),
        stamphog_connected=_stamphog_connected(team_id),
    )


def get_review_user_preferences(team_id: int, user_id: int) -> ReviewUserPreferences:
    """The user's effective review preferences on the project. Reading never creates a row."""
    team_id = resolve_effective_team_id(team_id)
    # Seed the authoring companion before any review has run: the "Create your own …" tasks
    # `skill-get` it over MCP, and this settings read backs the Code review tab's always-called
    # endpoint. `team_id` is already the effective (root) team, the same team the review runs
    # under, so the skill lands where the sandbox agent's `skill-get` will look.
    seed_canonicals_tolerantly(team_id, sync_canonical_authoring)
    return _user_preferences(team_id, ReviewUserSettings.load_preferences(team_id, user_id))


def update_review_user_preferences(team_id: int, user_id: int, changes: Mapping[str, object]) -> ReviewUserPreferences:
    """Apply `changes` to the user's preferences. A value equal to the inherited one clears the user's own value.

    Raises `InvalidPreference` for an unknown key or an invalid value.
    """
    # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its filter
    # but not the create kwargs, and mismatched ids mean a never-matching get plus 500s on re-read.
    team_id = resolve_effective_team_id(team_id)
    return _user_preferences(team_id, ReviewUserSettings.save_preference_changes(team_id, user_id, changes))


# Repository settings. Each function takes the root project id: the views resolve it once, because
# their permission checks need it too.


def _user_ref(user: User | None) -> ReviewUserRef | None:
    if user is None:
        return None
    return ReviewUserRef(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _person_entry(person: ReviewRepositoryPerson) -> ReviewRepositoryPersonEntry:
    user = _user_ref(person.user)
    assert user is not None
    return ReviewRepositoryPersonEntry(id=person.id, user=user, kind=ReviewRepositoryPersonKind(person.kind))


def _person_entries(people: Sequence[ReviewRepositoryPerson]) -> list[ReviewRepositoryPersonEntry]:
    return [_person_entry(person) for person in people]


def _repository_settings(
    row: ReviewRepository, people: Mapping[UUID | None, Sequence[ReviewRepositoryPerson]]
) -> ReviewRepositorySettings:
    return ReviewRepositorySettings(
        id=row.id,
        installation_id=row.installation_id,
        github_repo_id=row.github_repo_id,
        full_name=row.full_name,
        selected=row.selected,
        flash_for=AutomaticFlashFor(row.flash_for) if row.flash_for is not None else None,
        people=_person_entries(people.get(row.id, [])),
        created_by=_user_ref(row.created_by),
        created_at=row.created_at,
    )


def _claim_info(claim: ReviewInstallationClaim) -> ReviewInstallationClaimInfo:
    return ReviewInstallationClaimInfo(
        id=claim.id,
        installation_id=claim.installation_id,
        scope=ReviewInstallationClaimScope(claim.scope),
        account_name=installation_account_name(claim.installation_id),
        created_by=_user_ref(claim.created_by),
        created_at=claim.created_at,
    )


def _installation_info(summary: InstallationSummary) -> ReviewInstallationInfo:
    return ReviewInstallationInfo(
        installation_id=summary.installation_id,
        account_name=summary.account_name,
        connected_by=_user_ref(summary.connected_by),
        claim_id=summary.claim.id if summary.claim is not None else None,
        scope=ReviewInstallationClaimScope(summary.claim.scope) if summary.claim is not None else None,
        all_taken_by=summary.all_taken_by,
    )


def _choice_info(choice: ReviewUserRepositoryChoice) -> ReviewRepositoryChoiceInfo:
    return ReviewRepositoryChoiceInfo(
        id=choice.id,
        installation_id=choice.installation_id,
        github_repo_id=choice.github_repo_id,
        full_name=choice.full_name,
        mode=ReviewUserRepositoryChoiceMode(choice.mode),
    )


def _overview_entry(entry: OverviewEntry) -> ReviewRepositoryOverviewEntry:
    repository = entry.repository
    exception = None
    if repository is not None and repository.flash_for is not None:
        exception = ReviewRepositoryException(
            flash_for=AutomaticFlashFor(repository.flash_for), people=_person_entries(entry.exception_people)
        )
    return ReviewRepositoryOverviewEntry(
        full_name=entry.full_name,
        github_repo_id=entry.github_repo_id,
        owner=entry.owner,
        owner_project=entry.owner_project,
        in_project=entry.in_project,
        selected=entry.selected,
        repository_id=repository.id if repository is not None else None,
        exception=exception,
        my_choice=ReviewUserRepositoryChoiceMode(entry.my_choice.mode) if entry.my_choice is not None else None,
        my_choice_id=entry.my_choice.id if entry.my_choice is not None else None,
        my_result=entry.my_result,
        inherited_result=entry.inherited_result,
        repository_result=entry.repository_result,
    )


def _project_repositories(team_id: int, user_id: int) -> ProjectRepositories:
    return ProjectRepositories(Team.objects.get(id=team_id), User.objects.get(id=user_id))


def _repository_choices(team_id: int, user_id: int) -> RepositoryChoices:
    return RepositoryChoices(Team.objects.get(id=team_id), User.objects.get(id=user_id))


def list_review_repositories(team_id: int, user_id: int) -> list[ReviewRepositorySettings]:
    """The repositories the project has settings for, oldest first."""
    rows = _project_repositories(team_id, user_id).repositories()
    people = load_people(team_id, [row.id for row in rows])
    return [_repository_settings(row, people) for row in rows]


def get_review_repository(team_id: int, user_id: int, repository_id: UUID) -> ReviewRepositorySettings | None:
    row = _project_repositories(team_id, user_id).repository(repository_id)
    if row is None:
        return None
    return _repository_settings(row, load_people(team_id, [row.id]))


def save_review_repository(
    team_id: int,
    user_id: int,
    *,
    installation_id: str,
    full_name: str,
    github_repo_id: int | None,
    selected: bool | None,
    flash_for: AutomaticFlashFor | None | Unset = UNSET,
) -> ReviewRepositoryWriteOutcome:
    """Include or remove a repository, or set or clear its exception. Omitted fields keep their value.

    Raises `OwnershipConflict` when another project holds the repository, and `RepositorySettingsError`
    when the rules forbid the write.
    """
    ref = RepositoryRef(installation_id=installation_id, github_repo_id=github_repo_id, full_name=full_name)
    result = _project_repositories(team_id, user_id).save_repository(ref, selected=selected, flash_for=flash_for)
    repository = None
    if result.repository is not None:
        repository = _repository_settings(result.repository, load_people(team_id, [result.repository.id]))
    return ReviewRepositoryWriteOutcome(repository=repository, taken_from=result.taken_from)


def delete_review_repository(team_id: int, user_id: int, repository_id: UUID) -> bool:
    """Remove the repository's settings and its lists. False when the project has no such repository."""
    return _project_repositories(team_id, user_id).delete_repository(repository_id)


def add_review_repository_person(
    team_id: int, user_id: int, repository_id: UUID | None, *, person_user_id: int, kind: ReviewRepositoryPersonKind
) -> bool:
    """Add a person to a list of a repository exception, or of the project rule when `repository_id` is None.

    True when added, False when the person was already on the list. Raises `PersonNotActiveMemberError`, and
    `RepositoryNotFoundError` when the project has no such repository.
    """
    repositories = _project_repositories(team_id, user_id)
    repository = None
    if repository_id is not None:
        repository = repositories.repository(repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"The project has no repository settings {repository_id}.")
    repositories.check_active_member(person_user_id)
    if repository is None:
        # The row exists first, so the activity log has an item to attach the list change to.
        ReviewProjectSettings.ensure(team_id)
    return repositories.add_person(repository, user_id=person_user_id, kind=kind)


def remove_review_repository_person(team_id: int, user_id: int, repository_id: UUID | None, person_id: UUID) -> bool:
    """Remove one entry from a list of a repository exception, or of the project rule when `repository_id` is None.

    False when the list has no such entry.
    """
    return _project_repositories(team_id, user_id).remove_person(repository_id, person_id)


def list_review_installation_claims(team_id: int, user_id: int) -> list[ReviewInstallationClaimInfo]:
    return [_claim_info(claim) for claim in _project_repositories(team_id, user_id).claims()]


def get_review_installation_claim(team_id: int, user_id: int, claim_id: UUID) -> ReviewInstallationClaimInfo | None:
    claim = _project_repositories(team_id, user_id).claim(claim_id)
    return _claim_info(claim) if claim is not None else None


def create_review_installation_claim(
    team_id: int, user_id: int, installation_id: str, scope: ReviewInstallationClaimScope
) -> ReviewInstallationClaimInfo:
    """Raises `OwnershipConflict` when another project takes all repositories, and `RepositorySettingsError`."""
    return _claim_info(_project_repositories(team_id, user_id).create_claim(installation_id, scope))


def update_review_installation_claim(
    team_id: int, user_id: int, claim_id: UUID, scope: ReviewInstallationClaimScope
) -> ReviewInstallationClaimInfo | None:
    """None when the project has no such claim. Raises `OwnershipConflict`."""
    repositories = _project_repositories(team_id, user_id)
    claim = repositories.claim(claim_id)
    if claim is None:
        return None
    return _claim_info(repositories.update_claim(claim, scope))


def delete_review_installation_claim(team_id: int, user_id: int, claim_id: UUID) -> bool:
    """Remove the claim and the project's repository settings there. False when there is no such claim."""
    repositories = _project_repositories(team_id, user_id)
    claim = repositories.claim(claim_id)
    if claim is None:
        return False
    repositories.delete_claim(claim)
    return True


def list_review_repository_choices(team_id: int, user_id: int) -> list[ReviewRepositoryChoiceInfo]:
    """The user's own repository choices in the project, by repository name."""
    return [_choice_info(choice) for choice in _repository_choices(team_id, user_id).choices()]


def save_review_repository_choice(
    team_id: int,
    user_id: int,
    *,
    installation_id: str,
    full_name: str,
    github_repo_id: int | None,
    mode: ReviewUserRepositoryChoiceMode,
) -> ReviewRepositoryChoiceOutcome:
    """Set the user's own choice for one repository. A value equal to the inherited one clears it.

    Raises `RepositorySettingsError` when the project does not review the repository.
    """
    ref = RepositoryRef(installation_id=installation_id, github_repo_id=github_repo_id, full_name=full_name)
    choice, decision = _repository_choices(team_id, user_id).save(ref, mode)
    return ReviewRepositoryChoiceOutcome(
        choice=_choice_info(choice) if choice is not None else None, my_result=decision
    )


def delete_review_repository_choice(team_id: int, user_id: int, choice_id: UUID) -> bool:
    """Clear one of the user's own choices. False when the user has no such choice."""
    return _repository_choices(team_id, user_id).delete(choice_id)


def get_review_project_settings(team_id: int, user_id: int) -> ReviewProjectSettingsInfo:
    """The project rule, its Full review defaults and people lists, and the connected installations."""
    row = ReviewProjectSettings.load(team_id)
    defaults = row.defaults
    return ReviewProjectSettingsInfo(
        flash_for=AutomaticFlashFor(row.flash_for),
        bot_prs=ReviewProjectSettingsBotPullRequests(row.bot_prs),
        urgency_threshold=defaults.urgency_threshold,
        celebrate_clean_reviews=defaults.celebrate_clean_reviews,
        people=_person_entries(load_people(team_id, [])[None]),
        installations=[
            _installation_info(summary) for summary in _project_repositories(team_id, user_id).installations()
        ],
    )


def update_review_project_settings(team_id: int, changes: Mapping[str, object]) -> None:
    """Apply `changes` to the project rule. Omitted keys keep their value.

    Raises `InvalidPreference` for an invalid Full review default.
    """
    ReviewProjectSettings.save_changes(team_id, changes)


def get_review_repository_overview(
    team_id: int,
    user_id: int,
    installation_id: str,
    *,
    search: str,
    view: RepositoryOverviewView,
    offset: int,
    limit: int,
) -> ReviewRepositoryOverviewPage:
    """One page of the repositories the installation can see, with this project's settings and the user's.

    Raises `RepositorySettingsError` when the project has no connection for the installation, and
    `GitHubRepositoryListError` when GitHub does not return the repository list.
    """
    repositories = _project_repositories(team_id, user_id)
    listed = repositories.installation_repositories(installation_id, search)
    overview = RepositoryOverview(repositories.team, repositories.user, installation_id, listed)
    entries, total = overview.page(view=view, offset=offset, limit=limit)
    folds = view == RepositoryOverviewView.DIFFERS or (view == RepositoryOverviewView.ALL and not search.strip())
    folded = overview.folded() if folds else []
    claim = repositories.claim_for(installation_id)
    return ReviewRepositoryOverviewPage(
        installation_id=installation_id,
        claim_scope=ReviewInstallationClaimScope(claim.scope) if claim is not None else None,
        entries=[_overview_entry(entry) for entry in entries],
        total=total,
        folded=len(folded),
        folded_preview=[entry.full_name for entry in folded[:FOLDED_PREVIEW_SIZE]],
        folded_result=folded[0].my_result if folded else None,
        my_choices_unlike_default=overview.choices_unlike_default(),
    )


# Review reads. Each function takes the root project id, like the repository settings.


def list_recent_reviews(team_id: int, user_id: int, scope: ReviewReportScope, limit: int) -> ReviewSummaryPage:
    """At most `limit` reviews: the visibly running ones first, then the completed ones, newest first."""
    return ReviewListing(team_id).recent(user_id, scope, limit)


def list_reviews_table(
    team_id: int,
    user_id: int,
    scope: ReviewReportScope,
    *,
    repository: str | None,
    review_mode: str | None,
    activity: ReviewActivityFilter | None,
    published: bool | None,
    limit: int,
    offset: int,
) -> ReviewTablePage:
    """One page of the reviews with a completed turn or a running one, most recent activity first.

    A filter that is None does not filter.
    """
    return ReviewListing(team_id).table(
        user_id,
        scope,
        repository=repository,
        review_mode=review_mode,
        activity=activity,
        published=published,
        limit=limit,
        offset=offset,
    )


def get_review_perspective_stats(team_id: int, user_id: int, scope: ReviewReportScope) -> ReviewPerspectiveStats:
    """How many findings each review skill raised across the recent completed reviews in scope, and how many stayed."""
    return ReviewListing(team_id).perspective_stats(user_id, scope)


def get_review_detail(team_id: int, report_id: UUID, run_index: int | None) -> ReviewDetail:
    """One completed turn of a review, the latest when `run_index` is None.

    Raises `ReviewNotFoundError` when the project has no such review with a completed turn, and
    `ReviewTurnNotFoundError` when the review has no completed turn `run_index`.
    """
    return ReviewListing(team_id).detail(report_id, run_index)
