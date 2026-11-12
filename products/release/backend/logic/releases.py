"""Business logic for release."""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from posthog.models.utils import strict_fetch

from ..facade.contracts import ReleaseNotFoundError
from ..models import Release


def list_releases(team_id: int) -> QuerySet[Release]:
    return strict_fetch(Release.objects.filter(team_id=team_id).select_related("owner").order_by("created_at", "id"))


def get_release(team_id: int, release_id: UUID) -> Release:
    release = Release.objects.filter(team_id=team_id, id=release_id).select_related("owner").first()
    if release is None:
        raise ReleaseNotFoundError(release_id)
    return release


def create_release(
    *,
    team_id: int,
    name: str,
    description: str,
    owner_id: int | None,
    feature_flag_ids: list[int],
    broadcast_ids: list[UUID],
) -> Release:
    return Release.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        owner_id=owner_id,
        feature_flag_ids=feature_flag_ids,
        broadcast_ids=broadcast_ids,
    )


def update_release(team_id: int, release_id: UUID, changes: dict) -> Release:
    release = get_release(team_id, release_id)
    for field, value in changes.items():
        setattr(release, field, value)
    release.save(update_fields=[*changes.keys(), "updated_at"])
    return get_release(team_id, release_id)


def delete_release(team_id: int, release_id: UUID) -> None:
    Release.objects.filter(team_id=team_id, id=release_id).delete()
