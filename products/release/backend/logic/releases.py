"""Business logic for release."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet

from posthog.models.utils import strict_fetch

from ..facade.contracts import MAX_LINKED, InvalidMergeError, ReleaseNotFoundError
from ..models import Release


def list_releases(team_id: int) -> QuerySet[Release]:
    return strict_fetch(Release.objects.filter(team_id=team_id).select_related("owner").order_by("created_at", "id"))


def list_catalog_releases(
    team_id: int,
    search: str,
    after: tuple[datetime, UUID] | None,
    *,
    owner_ids: list[int] | None = None,
    oldest_first: bool = False,
) -> QuerySet[Release]:
    releases = Release.objects.filter(team_id=team_id)
    if after:
        created_at, release_id = after
        if oldest_first:
            releases = releases.filter(Q(created_at__gt=created_at) | Q(created_at=created_at, id__gt=release_id))
        else:
            releases = releases.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=release_id))
    if search:
        releases = releases.filter(name__icontains=search)
    if owner_ids:
        releases = releases.filter(owner_id__in=owner_ids)
    order = ("created_at", "id") if oldest_first else ("-created_at", "-id")
    return (
        releases.select_related("owner")
        .only(
            "id",
            "name",
            "created_at",
            "auto_named",
            "feature_flag_ids",
            "owner__id",
            "owner__uuid",
            "owner__first_name",
            "owner__last_name",
            "owner__email",
            "owner__is_active",
        )
        .order_by(*order)
    )


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
    survey_ids: list[UUID],
    insight_ids: list[int],
) -> Release:
    return Release.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        owner_id=owner_id,
        feature_flag_ids=feature_flag_ids,
        broadcast_ids=broadcast_ids,
        survey_ids=survey_ids,
        insight_ids=insight_ids,
    )


def update_release(team_id: int, release_id: UUID, changes: dict) -> Release:
    release = get_release(team_id, release_id)
    if "name" in changes:
        changes = {**changes, "auto_named": False}
    for field, value in changes.items():
        setattr(release, field, value)
    release.save(update_fields=[*changes.keys(), "updated_at"])
    return get_release(team_id, release_id)


LINKED_NOUNS = {
    "feature_flag_ids": "flags",
    "broadcast_ids": "broadcasts",
    "survey_ids": "surveys",
    "insight_ids": "insights",
}
LINKED_FIELDS = tuple(LINKED_NOUNS)


def merge_releases(
    team_id: int,
    target_id: UUID,
    source_ids: list[UUID],
    name: str | None = None,
    check: Callable[[list[Release]], None] | None = None,
) -> Release:
    with transaction.atomic():
        found = {
            release.id: release
            for release in Release.objects.select_for_update()
            .filter(team_id=team_id, id__in=[target_id, *source_ids])
            .order_by("id")
        }
        for release_id in [target_id, *source_ids]:
            if release_id not in found:
                raise ReleaseNotFoundError(release_id)
        target = found[target_id]
        sources = [found[release_id] for release_id in source_ids]
        if check:
            check([target, *sources])
        for field in LINKED_FIELDS:
            merged = list(
                dict.fromkeys(
                    [*getattr(target, field), *(item for source in sources for item in getattr(source, field))]
                )
            )
            if len(merged) > MAX_LINKED:
                raise InvalidMergeError(
                    f"The merged release would link {len(merged)} {LINKED_NOUNS[field]}, more than the {MAX_LINKED} a release can hold."
                )
            setattr(target, field, merged)
        target.owner_id = target.owner_id or next((source.owner_id for source in sources if source.owner_id), None)
        target.description = target.description or next(
            (source.description for source in sources if source.description), ""
        )
        renamed = name is not None and name != "" and name != target.name
        if renamed and name is not None:
            target.name = name
            target.auto_named = False
        target.save(
            update_fields=[
                *LINKED_FIELDS,
                "owner",
                "description",
                *(["name", "auto_named"] if renamed else []),
                "updated_at",
            ]
        )
        Release.objects.filter(team_id=team_id, id__in=source_ids).delete()
    return get_release(team_id, target_id)


def delete_release(team_id: int, release_id: UUID) -> None:
    Release.objects.filter(team_id=team_id, id=release_id).delete()
