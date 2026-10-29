"""A member's own standing instructions to stay off automatic reviewer selection, as DTOs.

Every function scopes to the instructions that name the given member, so a member never reads
or changes another member's instruction.
"""

from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.models import SignalReviewerExclusion
from products.signals.backend.repo_corrections import sanitized_repository as sanitized_repository
from products.signals.backend.reviewer_exclusions import (
    DuplicateExclusion as DuplicateExclusion,
    create_exclusion,
    revise_exclusion,
    revoke_exclusion,
)
from products.signals.backend.reviewer_rules import ReviewerWriteError as ReviewerWriteError
from products.signals.backend.views import remove_suggested_reviewer

ReviewerExclusionStatus = SignalReviewerExclusion.Status


class ReviewerExclusionNotFound(Exception):
    pass


class RevokedExclusion(ValueError):
    pass


class PathWithoutRepository(ValueError):
    pass


@frozen
class ReviewerExclusion:
    id: UUID
    repository: str
    path_prefix: str
    instruction: str
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


def _to_dto(row: SignalReviewerExclusion) -> ReviewerExclusion:
    return ReviewerExclusion(
        id=row.id,
        repository=row.repository,
        path_prefix=row.path_prefix,
        instruction=row.instruction,
        status=row.status,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _own(team_id: int, user: User) -> QuerySet[SignalReviewerExclusion]:
    return SignalReviewerExclusion.objects.for_team(team_id).filter(subject_user_uuid=user.uuid)


def list_own_exclusions(*, team_id: int, user: User) -> list[ReviewerExclusion]:
    return [_to_dto(row) for row in _own(team_id, user).order_by("-created_at", "-id")]


def get_own_exclusion(*, team_id: int, user: User, exclusion_id: UUID) -> ReviewerExclusion:
    row = _own(team_id, user).filter(id=exclusion_id).first()
    if row is None:
        raise ReviewerExclusionNotFound()
    return _to_dto(row)


def create_own_exclusion(
    *, team_id: int, user: User, instruction: str, repository: str, path_prefix: str
) -> tuple[ReviewerExclusion, bool]:
    """Create the member's instruction, or return the active one for the same area and whether it is new."""
    row, created = create_exclusion(
        team_id=team_id,
        actor_id=user.id,
        instruction=instruction,
        subject_user_uuid=user.uuid,
        subject_github_login=user.get_github_login(include_team_fallback=False),
        repository=repository,
        path_prefix=path_prefix,
    )
    return _to_dto(row), created


def revise_own_exclusion(
    *,
    team_id: int,
    user: User,
    exclusion_id: UUID,
    instruction: str | None,
    repository: str | None,
    path_prefix: str | None,
) -> ReviewerExclusion:
    with transaction.atomic():
        # Check the merged area against the locked row, so a concurrent amend cannot break the constraint.
        locked = _own(team_id, user).select_for_update().filter(id=exclusion_id).first()
        if locked is None:
            raise ReviewerExclusionNotFound()
        if locked.status != ReviewerExclusionStatus.ACTIVE:
            raise RevokedExclusion("A revoked instruction cannot change.")
        if (path_prefix if path_prefix is not None else locked.path_prefix) and not (
            repository if repository is not None else locked.repository
        ):
            raise PathWithoutRepository("Give a repository for a path.")
        row = revise_exclusion(
            team_id=team_id,
            exclusion_id=locked.id,
            actor_id=user.id,
            instruction=instruction,
            repository=repository,
            path_prefix=path_prefix,
        )
    return _to_dto(row)


def revoke_own_exclusion(*, team_id: int, user: User, exclusion_id: UUID) -> ReviewerExclusion:
    with transaction.atomic():
        if not _own(team_id, user).filter(id=exclusion_id).exists():
            raise ReviewerExclusionNotFound()
        row = revoke_exclusion(team_id=team_id, exclusion_id=exclusion_id, actor_id=user.id)
    return _to_dto(row)


def remove_report_reviewer(
    *, team: Team, report_id: str, user: User, scoped_team_ids: tuple[int, ...] | None, was_impersonated: bool
) -> bool:
    """Take the member off one report's suggested reviewers. Returns whether they were on it."""
    return remove_suggested_reviewer(
        team=team,
        report_id=report_id,
        user=user,
        scoped_team_ids=scoped_team_ids,
        was_impersonated=was_impersonated,
    )
