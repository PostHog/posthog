"""Business logic for release."""

from __future__ import annotations

from uuid import UUID

from ..models import Release


def list_releases() -> list[Release]:
    return list(Release.objects.select_related("owner").order_by("created_at"))


def get_release(release_id: UUID) -> Release:
    return Release.objects.select_related("owner").get(id=release_id)


def create_release(
    *, team_id: int, name: str, description: str, owner_id: int | None, feature_flag_ids: list[int]
) -> Release:
    return Release.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        owner_id=owner_id,
        feature_flag_ids=feature_flag_ids,
    )


def update_release(release_id: UUID, changes: dict) -> Release:
    feature = Release.objects.get(id=release_id)
    for field, value in changes.items():
        setattr(feature, field, value)
    feature.save()
    return get_release(release_id)


def delete_release(release_id: UUID) -> None:
    Release.objects.filter(id=release_id).delete()
