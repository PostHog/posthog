"""Which automatic review a pull request author gets in a repository that a project reviews.

The highest level that has an opinion wins:

1. The author's choice for this repository.
2. The author's default, unless it is "follow".
3. The repository exception of the owning project.
4. The project rule: Flash for everyone except the excepted people, Flash only for the listed
   people, or Flash only for people who opt in.

Bot authors, and authors who map to no project member, have no choices. They get automatic Flash
only when the project reviews bot pull requests.

`AutomaticReviewRule.resolve` is pure, so the dispatch, the workflow re-check, and the settings API
all give the same answer. The loaders below read the rows it needs.
"""

from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from django.db import models

from posthog.dataclasses import frozen

from products.review_hog.backend.models import (
    AutomaticFlashFor,
    ReviewProjectSettings,
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
    ReviewUserSettings,
)
from products.review_hog.backend.ownership import RepositoryRef
from products.review_hog.backend.preferences import DefaultReviewMode


class AutomaticReviewReason(models.TextChoices):
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


_RULE_REASONS: dict[tuple[bool, str], AutomaticReviewReason] = {
    (True, "everyone"): AutomaticReviewReason.REPOSITORY_EVERYONE,
    (True, "excepted"): AutomaticReviewReason.REPOSITORY_EXCEPTED,
    (True, "listed"): AutomaticReviewReason.REPOSITORY_LISTED,
    (True, "not_listed"): AutomaticReviewReason.REPOSITORY_NOT_LISTED,
    (True, "opt_in"): AutomaticReviewReason.REPOSITORY_OPT_IN,
    (False, "everyone"): AutomaticReviewReason.PROJECT_EVERYONE,
    (False, "excepted"): AutomaticReviewReason.PROJECT_EXCEPTED,
    (False, "listed"): AutomaticReviewReason.PROJECT_LISTED,
    (False, "not_listed"): AutomaticReviewReason.PROJECT_NOT_LISTED,
    (False, "opt_in"): AutomaticReviewReason.PROJECT_OPT_IN,
}


def is_bot_login(github_login: str) -> bool:
    # GitHub App accounts, the only accounts GitHub types as "Bot", end their login in "[bot]".
    return github_login.lower().endswith("[bot]")


@frozen
class AutomaticReviewDecision:
    flash: bool
    reason: AutomaticReviewReason


@frozen
class AuthorChoice:
    # None when the GitHub author maps to no PostHog user.
    user_id: int | None
    is_bot: bool
    default_mode: DefaultReviewMode
    repository_choice: ReviewUserRepositoryChoice.Mode | None


@frozen
class FlashRule:
    """One level's rule, the project rule or a repository exception, with its people lists."""

    flash_for: AutomaticFlashFor
    listed_user_ids: frozenset[int]
    excepted_user_ids: frozenset[int]

    @classmethod
    def from_people(cls, flash_for: str, people: Sequence[ReviewRepositoryPerson]) -> "FlashRule":
        return cls(
            flash_for=AutomaticFlashFor(flash_for),
            listed_user_ids=frozenset(
                person.user_id for person in people if person.kind == ReviewRepositoryPerson.Kind.LISTED
            ),
            excepted_user_ids=frozenset(
                person.user_id for person in people if person.kind == ReviewRepositoryPerson.Kind.EXCEPTED
            ),
        )

    def decide(self, user_id: int, *, is_repository: bool) -> AutomaticReviewDecision:
        if self.flash_for == AutomaticFlashFor.EVERYONE:
            flash, outcome = (False, "excepted") if user_id in self.excepted_user_ids else (True, "everyone")
        elif self.flash_for == AutomaticFlashFor.LISTED:
            flash, outcome = (True, "listed") if user_id in self.listed_user_ids else (False, "not_listed")
        else:
            flash, outcome = False, "opt_in"
        return AutomaticReviewDecision(flash=flash, reason=_RULE_REASONS[(is_repository, outcome)])


@frozen
class AutomaticReviewRule:
    project: FlashRule
    # None when the repository follows the project rule.
    repository: FlashRule | None
    review_bots: bool

    def resolve(self, author: AuthorChoice) -> AutomaticReviewDecision:
        if author.is_bot or author.user_id is None:
            if self.review_bots:
                return AutomaticReviewDecision(flash=True, reason=AutomaticReviewReason.BOT_REVIEWED)
            return AutomaticReviewDecision(flash=False, reason=AutomaticReviewReason.BOT_SKIPPED)
        if author.repository_choice is not None:
            return AutomaticReviewDecision(
                flash=author.repository_choice == ReviewUserRepositoryChoice.Mode.FLASH,
                reason=AutomaticReviewReason.OWN_REPOSITORY_CHOICE,
            )
        if author.default_mode != DefaultReviewMode.FOLLOW:
            return AutomaticReviewDecision(
                flash=author.default_mode == DefaultReviewMode.FLASH, reason=AutomaticReviewReason.OWN_DEFAULT
            )
        if self.repository is not None:
            return self.repository.decide(author.user_id, is_repository=True)
        return self.project.decide(author.user_id, is_repository=False)


def load_people(team_id: int, repository_ids: Iterable[UUID]) -> dict[UUID | None, list[ReviewRepositoryPerson]]:
    """People lists keyed by repository id. The key None holds the lists of the project rule."""
    people: dict[UUID | None, list[ReviewRepositoryPerson]] = {None: []}
    people.update({repository_id: [] for repository_id in repository_ids})
    repository_filter = models.Q(repository_id__in=[key for key in people if key is not None])
    rows = (
        ReviewRepositoryPerson.objects.for_team(team_id)
        .filter(repository_filter | models.Q(repository__isnull=True))
        .select_related("user")
        .order_by("created_at")
    )
    for person in rows:
        people[person.repository_id].append(person)
    return people


@frozen
class ProjectRuleContext:
    """What a project needs to resolve its rule in many repositories without another query."""

    settings: ReviewProjectSettings
    people: Mapping[UUID | None, Sequence[ReviewRepositoryPerson]]

    @classmethod
    def load(cls, team_id: int, repositories: Iterable[ReviewRepository]) -> "ProjectRuleContext":
        return cls(
            settings=ReviewProjectSettings.load(team_id),
            people=load_people(team_id, [repository.id for repository in repositories]),
        )

    def rule_for(self, repository: ReviewRepository | None) -> AutomaticReviewRule:
        exception = None
        if repository is not None and repository.flash_for is not None:
            exception = FlashRule.from_people(repository.flash_for, self.people.get(repository.id, []))
        return AutomaticReviewRule(
            project=FlashRule.from_people(self.settings.flash_for, self.people.get(None, [])),
            repository=exception,
            review_bots=self.settings.bot_prs == ReviewProjectSettings.BotPullRequests.RUN,
        )


@frozen
class AuthorPreferences:
    """An author's own choices across all repositories of a project."""

    user_id: int | None
    is_bot: bool
    default_mode: DefaultReviewMode
    choices: Sequence[ReviewUserRepositoryChoice]

    def choice_for(self, repository: RepositoryRef) -> ReviewUserRepositoryChoice | None:
        candidates = [choice for choice in self.choices if choice.installation_id == repository.installation_id]
        if repository.github_repo_id is not None:
            for choice in candidates:
                if choice.github_repo_id == repository.github_repo_id:
                    return choice
        name = repository.full_name.lower()
        for choice in candidates:
            # A name match with another id is an older repository that had this name.
            same_repository = choice.github_repo_id is None or repository.github_repo_id is None
            if choice.full_name.lower() == name and same_repository:
                return choice
        return None

    def for_repository(self, repository: RepositoryRef) -> AuthorChoice:
        choice = self.choice_for(repository)
        return AuthorChoice(
            user_id=self.user_id,
            is_bot=self.is_bot,
            default_mode=self.default_mode,
            repository_choice=ReviewUserRepositoryChoice.Mode(choice.mode) if choice is not None else None,
        )


def load_author_preferences(team_id: int, *, user_id: int | None, is_bot: bool) -> AuthorPreferences:
    if user_id is None or is_bot:
        return AuthorPreferences(user_id=user_id, is_bot=is_bot, default_mode=DefaultReviewMode.FOLLOW, choices=())
    return AuthorPreferences(
        user_id=user_id,
        is_bot=is_bot,
        default_mode=ReviewUserSettings.load_preferences(team_id, user_id).default_review_mode,
        choices=tuple(ReviewUserRepositoryChoice.objects.for_team(team_id).filter(user_id=user_id)),
    )


def decide_automatic_review(
    team_id: int,
    repository: RepositoryRef,
    row: ReviewRepository | None,
    *,
    author_user_id: int | None,
    author_login: str,
) -> AutomaticReviewDecision:
    """The decision for one author in a repository that `team_id` owns. `row` is that project's row."""
    rule = ProjectRuleContext.load(team_id, [row] if row is not None else []).rule_for(row)
    author = load_author_preferences(team_id, user_id=author_user_id, is_bot=is_bot_login(author_login))
    return rule.resolve(author.for_repository(repository))
