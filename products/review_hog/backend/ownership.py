"""Which project reviews a GitHub repository.

A repository belongs to at most one project, like GitHub's install picker:

1. A project that selected the repository (`ReviewRepository.selected`), or that has a row for it
   and takes all repositories of the installation, owns it.
2. Else the project that takes all repositories of the installation owns it.
3. Else no project owns it: no automatic review, and the label trigger reports "not set up".

`resolve_owner` is pure. `RepositoryOwnership` loads the rows across projects, because ownership is
a question about every project that shares the installation. `OwnedRepositoryPrefilter` lets the
webhook handler drop events of repositories nobody reviews before it queues a task.
"""

import logging
from collections.abc import Sequence
from typing import Any

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.dataclasses import frozen
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.models.integration import Integration
from posthog.utils import safe_cache_delete

from products.review_hog.backend.models import ReviewInstallationClaim, ReviewRepository

logger = logging.getLogger(__name__)


@frozen
class RepositoryRef:
    installation_id: str
    # None when the caller only knows the name, for example the label trigger.
    github_repo_id: int | None
    full_name: str

    def matches(self, row: ReviewRepository) -> bool:
        if self.github_repo_id is not None and row.github_repo_id == self.github_repo_id:
            return True
        # A name match with another id is an older repository that had this name.
        same_repository = row.github_repo_id is None or self.github_repo_id is None
        return same_repository and row.full_name.lower() == self.full_name.lower()


@frozen
class RepositoryOwner:
    team_id: int
    installation_id: str
    row: ReviewRepository | None


def find_matching_row(ref: RepositoryRef, rows: Sequence[ReviewRepository]) -> ReviewRepository | None:
    """The row for this repository: an id match first, then a name match."""
    if ref.github_repo_id is not None:
        for row in rows:
            if row.github_repo_id == ref.github_repo_id:
                return row
    for row in rows:
        if ref.matches(row):
            return row
    return None


def resolve_owner(
    ref: RepositoryRef, rows: Sequence[ReviewRepository], all_claim: ReviewInstallationClaim | None
) -> RepositoryOwner | None:
    """The owning project of one repository, from the installation's rows and its "all" claim."""
    row = find_matching_row(ref, rows)
    if row is not None and (row.selected or (all_claim is not None and all_claim.team_id == row.team_id)):
        return RepositoryOwner(team_id=row.team_id, installation_id=ref.installation_id, row=row)
    if all_claim is not None:
        return RepositoryOwner(team_id=all_claim.team_id, installation_id=ref.installation_id, row=None)
    return None


class RepositoryOwnership:
    @staticmethod
    def rows_for(ref: RepositoryRef) -> list[ReviewRepository]:
        # Unscoped on purpose: a repository can belong to any project. The name and the id identify
        # it, not the installation, so a reinstall of the GitHub App keeps the rows.
        name_or_id = Q(full_name__iexact=ref.full_name)
        if ref.github_repo_id is not None:
            name_or_id |= Q(github_repo_id=ref.github_repo_id)
        return list(ReviewRepository.objects.unscoped().filter(name_or_id))

    @staticmethod
    def all_claim(installation_id: str) -> ReviewInstallationClaim | None:
        return (
            ReviewInstallationClaim.objects.unscoped()
            .filter(installation_id=installation_id, scope=ReviewInstallationClaim.Scope.ALL)
            .first()
        )

    @classmethod
    def find(cls, ref: RepositoryRef, *, backfill: bool = False) -> RepositoryOwner | None:
        """The owning project. Only a signed GitHub webhook may pass `backfill=True`.

        The backfill writes the id and the name of `ref` onto a row of any project, so a ref built
        from client input must never reach it.
        """
        owner = resolve_owner(ref, cls.rows_for(ref), cls.all_claim(ref.installation_id))
        if backfill and owner is not None and owner.row is not None:
            cls._backfill(owner.row, ref)
        return owner

    @staticmethod
    def _backfill(row: ReviewRepository, ref: RepositoryRef) -> None:
        """Store the repository id the first time it shows, and the current name after a rename."""
        updates: dict[str, Any] = {}
        if row.github_repo_id is None and ref.github_repo_id is not None:
            updates["github_repo_id"] = ref.github_repo_id
        if ref.github_repo_id is not None and row.full_name != ref.full_name:
            updates["full_name"] = ref.full_name
        if not updates:
            return
        try:
            # A plain update, because bookkeeping must not add an activity log entry. The savepoint
            # keeps a unique violation from breaking a surrounding transaction.
            with transaction.atomic():
                ReviewRepository.objects.unscoped().filter(id=row.id).update(**updates)
        except Exception:
            # Another row can hold the new name or id after an unusual rename. The match still holds.
            logger.warning("Could not backfill ReviewHog repository %s", row.id, exc_info=True)
            return
        OwnedRepositoryPrefilter.invalidate(row.installation_id)

    @staticmethod
    def installation_ids_for_account(account_login: str) -> list[str]:
        """The installations of the PostHog GitHub App on one GitHub account, from any project."""
        installation_ids = (
            Integration.objects.filter(kind="github", config__account__name__iexact=account_login)
            .values_list("integration_id", flat=True)
            .distinct()
        )
        return sorted({installation_id for installation_id in installation_ids if installation_id})

    @classmethod
    def find_by_name(cls, full_name: str) -> RepositoryOwner | None:
        """Ownership when only the name is known. The account login in the name finds the installation."""
        account_login, _, _ = full_name.partition("/")
        for installation_id in cls.installation_ids_for_account(account_login):
            owner = cls.find(RepositoryRef(installation_id=installation_id, github_repo_id=None, full_name=full_name))
            if owner is not None:
                return owner
        return None


class OwnedRepositoryPrefilter:
    """A cached summary of which repositories of an installation any project reviews.

    The webhook handler uses it to drop pull request events of repositories nobody reviews, so it
    queues no task for them. `RepositoryOwnership.find` stays the source of truth: the cache is only
    a prefilter. The receivers below delete the key on every change, and the TTL caps staleness for
    writes that bypass the ORM signals.
    """

    TTL_SECONDS = 5 * 60
    STATEMENT_TIMEOUT_MS = 500

    @staticmethod
    def cache_key(installation_id: str) -> str:
        return f"review_hog:owned_repositories:{installation_id}"

    @staticmethod
    def load(installation_id: str) -> dict[str, Any]:
        # JSON-shaped values only, because the cache serializes them.
        takes_all = ReviewInstallationClaim.objects.unscoped().filter(
            installation_id=installation_id, scope=ReviewInstallationClaim.Scope.ALL
        )
        selected = ReviewRepository.objects.unscoped().filter(installation_id=installation_id, selected=True)
        rows = list(selected.values_list("full_name", "github_repo_id"))
        return {
            "all": takes_all.exists(),
            "names": sorted({full_name.lower() for full_name, _ in rows}),
            "ids": sorted({github_repo_id for _, github_repo_id in rows if github_repo_id is not None}),
        }

    @classmethod
    def load_bounded(cls, installation_id: str) -> dict[str, Any]:
        # The webhook handler reads inside the request, so a slow read must not hold the delivery.
        with bounded_statement_timeout(cls.STATEMENT_TIMEOUT_MS, models=[ReviewInstallationClaim, ReviewRepository]):
            return cls.load(installation_id)

    @classmethod
    def may_be_owned(cls, ref: RepositoryRef) -> bool:
        try:
            summary = cache.get_or_set(
                cls.cache_key(ref.installation_id), lambda: cls.load_bounded(ref.installation_id), cls.TTL_SECONDS
            )
            if not isinstance(summary, dict):
                summary = cls.load_bounded(ref.installation_id)
        except Exception:
            # Fail open: the task checks ownership again, and a Redis blip must not stop reviews.
            logger.warning("Could not read the owned ReviewHog repositories; queueing the event", exc_info=True)
            return True
        return (
            bool(summary.get("all"))
            or ref.full_name.lower() in summary.get("names", [])
            or ref.github_repo_id in summary.get("ids", [])
        )

    @classmethod
    def invalidate(cls, installation_id: str) -> None:
        key = cls.cache_key(installation_id)
        safe_cache_delete(key)
        # A reader between this delete and the commit can cache the old rows again.
        transaction.on_commit(lambda: safe_cache_delete(key))


@receiver(post_save, sender=ReviewRepository)
@receiver(post_save, sender=ReviewInstallationClaim)
def _invalidate_owned_repositories_on_save(
    sender: type[ReviewRepository | ReviewInstallationClaim],
    instance: ReviewRepository | ReviewInstallationClaim,
    **kwargs: Any,
) -> None:
    OwnedRepositoryPrefilter.invalidate(instance.installation_id)


@receiver(post_delete, sender=ReviewRepository)
@receiver(post_delete, sender=ReviewInstallationClaim)
def _invalidate_owned_repositories_on_delete(
    sender: type[ReviewRepository | ReviewInstallationClaim],
    instance: ReviewRepository | ReviewInstallationClaim,
    **kwargs: Any,
) -> None:
    OwnedRepositoryPrefilter.invalidate(instance.installation_id)
