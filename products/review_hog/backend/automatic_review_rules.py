"""Which automatic review a pull request author gets in an added repository.

Three levels decide, and the highest one that has an opinion wins:

1. Bots, when the repository excludes them.
2. The author's own choice: a per-repository choice, else their default unless it is "follow".
3. The repository's rule: Flash for everyone except the excepted people, or Flash only for the
   listed people.

`RepositoryReviewRule.resolve` is pure, so the dispatch, the workflow re-check, and the settings API
all give the same answer. The loaders below read the rows it needs.
"""

from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from django.db import models

from posthog.dataclasses import frozen

from products.review_hog.backend.models import (
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
    ReviewUserSettings,
)


class AutomaticReviewMode(models.TextChoices):
    FLASH = "flash", "Flash"
    FULL = "full", "Full"
    NONE = "none", "No automatic review"


class AutomaticReviewReason(models.TextChoices):
    BOT_EXCLUDED = "bot_excluded", "Bots are excluded"
    OWN_REPOSITORY_CHOICE = "own_repository_choice", "Own choice for this repository"
    OWN_DEFAULT = "own_default", "Own default"
    EVERYONE = "everyone", "Repository reviews everyone"
    EXCEPTED = "excepted", "Excepted by the repository"
    LISTED = "listed", "Listed by the repository"
    NOT_LISTED = "not_listed", "Not listed by the repository"


_OWN_CHOICE_MODES: dict[str, AutomaticReviewMode] = {
    "flash": AutomaticReviewMode.FLASH,
    "full": AutomaticReviewMode.FULL,
    "off": AutomaticReviewMode.NONE,
}


def is_bot_login(github_login: str) -> bool:
    # GitHub App accounts, the only accounts GitHub types as "Bot", end their login in "[bot]".
    return github_login.lower().endswith("[bot]")


@frozen
class AutomaticReviewDecision:
    mode: AutomaticReviewMode
    reason: AutomaticReviewReason


@frozen
class AuthorChoice:
    # None when the GitHub author has no PostHog user, so no own choice and no list can match.
    user_id: int | None
    is_bot: bool
    default_mode: ReviewUserSettings.DefaultReviewMode
    repository_choice: ReviewUserRepositoryChoice.Mode | None


@frozen
class AuthorPreferences:
    """An author's own choices across all repositories of a project."""

    user_id: int | None
    is_bot: bool
    default_mode: ReviewUserSettings.DefaultReviewMode
    repository_choices: Mapping[UUID, ReviewUserRepositoryChoice.Mode]

    def for_repository(self, repository_id: UUID) -> AuthorChoice:
        return AuthorChoice(
            user_id=self.user_id,
            is_bot=self.is_bot,
            default_mode=self.default_mode,
            repository_choice=self.repository_choices.get(repository_id),
        )


@frozen
class RepositoryReviewRule:
    flash_for: ReviewRepository.FlashFor
    exclude_bots: bool
    listed_user_ids: frozenset[int]
    excepted_user_ids: frozenset[int]

    @classmethod
    def for_repository(
        cls, repository: ReviewRepository, people: Sequence[ReviewRepositoryPerson]
    ) -> "RepositoryReviewRule":
        return cls(
            flash_for=ReviewRepository.FlashFor(repository.flash_for),
            exclude_bots=repository.exclude_bots,
            listed_user_ids=frozenset(
                person.user_id for person in people if person.kind == ReviewRepositoryPerson.Kind.LISTED
            ),
            excepted_user_ids=frozenset(
                person.user_id for person in people if person.kind == ReviewRepositoryPerson.Kind.EXCEPTED
            ),
        )

    def resolve(self, author: AuthorChoice) -> AutomaticReviewDecision:
        if author.is_bot and self.exclude_bots:
            return AutomaticReviewDecision(mode=AutomaticReviewMode.NONE, reason=AutomaticReviewReason.BOT_EXCLUDED)
        if author.repository_choice is not None:
            return AutomaticReviewDecision(
                mode=_OWN_CHOICE_MODES[author.repository_choice],
                reason=AutomaticReviewReason.OWN_REPOSITORY_CHOICE,
            )
        if author.default_mode != ReviewUserSettings.DefaultReviewMode.FOLLOW:
            return AutomaticReviewDecision(
                mode=_OWN_CHOICE_MODES[author.default_mode], reason=AutomaticReviewReason.OWN_DEFAULT
            )
        if self.flash_for == ReviewRepository.FlashFor.EVERYONE:
            if author.user_id in self.excepted_user_ids:
                return AutomaticReviewDecision(mode=AutomaticReviewMode.NONE, reason=AutomaticReviewReason.EXCEPTED)
            return AutomaticReviewDecision(mode=AutomaticReviewMode.FLASH, reason=AutomaticReviewReason.EVERYONE)
        if author.user_id in self.listed_user_ids:
            return AutomaticReviewDecision(mode=AutomaticReviewMode.FLASH, reason=AutomaticReviewReason.LISTED)
        return AutomaticReviewDecision(mode=AutomaticReviewMode.NONE, reason=AutomaticReviewReason.NOT_LISTED)


def find_repository(team_id: int, full_name: str) -> ReviewRepository | None:
    return ReviewRepository.objects.for_team(team_id).filter(full_name__iexact=full_name).first()


def load_repository_people(team_id: int, repository_ids: Iterable[UUID]) -> dict[UUID, list[ReviewRepositoryPerson]]:
    people: dict[UUID, list[ReviewRepositoryPerson]] = {repository_id: [] for repository_id in repository_ids}
    rows = (
        ReviewRepositoryPerson.objects.for_team(team_id)
        .filter(repository_id__in=list(people))
        .select_related("user")
        .order_by("created_at")
    )
    for person in rows:
        people[person.repository_id].append(person)
    return people


def load_author_preferences(team_id: int, *, user_id: int | None, is_bot: bool) -> AuthorPreferences:
    if user_id is None:
        return AuthorPreferences(
            user_id=None,
            is_bot=is_bot,
            default_mode=ReviewUserSettings.DefaultReviewMode.FOLLOW,
            repository_choices={},
        )
    choices = ReviewUserRepositoryChoice.objects.for_team(team_id).filter(user_id=user_id)
    return AuthorPreferences(
        user_id=user_id,
        is_bot=is_bot,
        default_mode=ReviewUserSettings.DefaultReviewMode(
            ReviewUserSettings.load(team_id, user_id).default_review_mode
        ),
        repository_choices={
            repository_id: ReviewUserRepositoryChoice.Mode(mode)
            for repository_id, mode in choices.values_list("repository_id", "mode")
        },
    )


def decide_automatic_review(
    repository: ReviewRepository, *, author_user_id: int | None, author_login: str
) -> AutomaticReviewDecision:
    people = load_repository_people(repository.team_id, [repository.id])[repository.id]
    author = load_author_preferences(repository.team_id, user_id=author_user_id, is_bot=is_bot_login(author_login))
    return RepositoryReviewRule.for_repository(repository, people).resolve(author.for_repository(repository.id))
