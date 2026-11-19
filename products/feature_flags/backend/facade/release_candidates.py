from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.db.models.signals import post_save

from posthog.scopes.catalog import APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey


@dataclass(frozen=True)
class ReleaseImportFlag:
    id: int
    key: str
    created_at: datetime
    created_by_id: int | None


def _visible(
    queryset: QuerySet, access_control: UserAccessControl | None, resource: APIScopeObject | None = None
) -> QuerySet:
    if access_control is None:
        return queryset
    return access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True, resource=resource)


def _survey_flag_ids(project_id: int, flag_ids: list[int]) -> set[int]:
    rows = (
        Survey.objects.filter(team__project_id=project_id)
        .filter(
            Q(targeting_flag_id__in=flag_ids)
            | Q(internal_targeting_flag_id__in=flag_ids)
            | Q(internal_response_sampling_flag_id__in=flag_ids)
        )
        .values_list("targeting_flag_id", "internal_targeting_flag_id", "internal_response_sampling_flag_id")
    )
    return {flag_id for row in rows for flag_id in row if flag_id in flag_ids}


def release_flag_creator_id(*, flag_id: int, team_id: int) -> int | None:
    return FeatureFlag.objects.filter(id=flag_id, team_id=team_id).values_list("created_by_id", flat=True).first()


def list_release_import_flags(
    *,
    team_id: int,
    project_id: int,
    access_control: UserAccessControl | None,
    flag_ids: list[int] | None = None,
) -> list[ReleaseImportFlag]:
    # nosemgrep: environment-model-scoped-by-project
    tour_flag_ids = ProductTour.all_objects.filter(
        team__project_id=project_id, internal_targeting_flag__isnull=False
    ).values_list("internal_targeting_flag_id", flat=True)
    candidates = FeatureFlag.objects.filter(team_id=team_id, deleted=False, archived=False, active=True)
    if flag_ids is not None:
        candidates = candidates.filter(id__in=flag_ids)
        survey_flag_ids = _survey_flag_ids(project_id, flag_ids)
    else:
        survey_flag_ids = Survey.get_internal_flag_ids(project_id=project_id)
    flags = (
        _visible(
            candidates.exclude(is_remote_configuration=True).exclude(
                Q(id__in=survey_flag_ids) | Q(id__in=tour_flag_ids)
            ),
            access_control,
        )
        .only("id", "key", "created_at", "created_by_id")
        .order_by("created_at", "id")
    )
    return [
        ReleaseImportFlag(
            id=flag.id,
            key=flag.key,
            created_at=flag.created_at,
            created_by_id=flag.created_by_id,
        )
        for flag in flags
    ]


@dataclass(frozen=True)
class ReleaseCatalogUser:
    id: int
    uuid: UUID
    first_name: str
    last_name: str
    email: str


@dataclass(frozen=True)
class ReleaseCatalogFlag:
    id: int
    key: str
    active: bool
    created_at: datetime
    created_by: ReleaseCatalogUser | None


def list_release_catalog_flags(
    *,
    team_id: int,
    project_id: int,
    access_control: UserAccessControl | None,
    search: str = "",
    created_by_ids: list[int] | None = None,
    oldest_first: bool = False,
    limit: int,
    offset: int = 0,
) -> tuple[list[ReleaseCatalogFlag], bool]:
    # nosemgrep: environment-model-scoped-by-project
    tour_flag_ids = ProductTour.all_objects.filter(
        team__project_id=project_id, internal_targeting_flag__isnull=False
    ).values_list("internal_targeting_flag_id", flat=True)
    surveys = Survey.objects.filter(team__project_id=project_id)
    flags = FeatureFlag.objects.filter(team_id=team_id, deleted=False, archived=False).exclude(
        Q(id__in=surveys.filter(targeting_flag__isnull=False).values("targeting_flag_id"))
        | Q(id__in=surveys.filter(internal_targeting_flag__isnull=False).values("internal_targeting_flag_id"))
        | Q(
            id__in=surveys.filter(internal_response_sampling_flag__isnull=False).values(
                "internal_response_sampling_flag_id"
            )
        )
        | Q(id__in=tour_flag_ids)
    )
    if search:
        flags = flags.filter(Q(key__icontains=search) | Q(name__icontains=search))
    if created_by_ids:
        flags = flags.filter(created_by_id__in=created_by_ids)
    order = ("created_at", "id") if oldest_first else ("-created_at", "-id")
    rows = list(
        _visible(flags, access_control, "feature_flag")
        .order_by(*order)
        .values_list(
            "id",
            "key",
            "active",
            "created_at",
            "created_by_id",
            "created_by__uuid",
            "created_by__first_name",
            "created_by__last_name",
            "created_by__email",
        )[offset : offset + limit + 1]
    )
    return [
        ReleaseCatalogFlag(
            id=flag_id,
            key=key,
            active=active,
            created_at=created_at,
            created_by=ReleaseCatalogUser(
                id=user_id, uuid=user_uuid, first_name=first_name, last_name=last_name, email=email
            )
            if user_id
            else None,
        )
        for flag_id, key, active, created_at, user_id, user_uuid, first_name, last_name, email in rows[:limit]
    ], len(rows) > limit


@dataclass(frozen=True)
class ReleaseFlagLabel:
    id: int
    key: str
    name: str


def release_flag_labels(*, team_id: int, flag_ids: list[int]) -> dict[int, ReleaseFlagLabel]:
    if not flag_ids:
        return {}
    rows = FeatureFlag.objects.filter(team_id=team_id, id__in=flag_ids, deleted=False).values_list("id", "key", "name")
    return {flag_id: ReleaseFlagLabel(id=flag_id, key=key, name=name or "") for flag_id, key, name in rows}


def release_flag_ids_matching(*, team_id: int, terms: list[str], limit: int) -> list[int]:
    if not terms:
        return []
    query = Q()
    for term in terms:
        query |= Q(key__icontains=term) | Q(name__icontains=term)
    return list(
        FeatureFlag.objects.filter(team_id=team_id, deleted=False)
        .filter(query)
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[:limit]
    )


def on_active_flag_saved(handler: Callable[[int, int], None]) -> None:
    def receiver(sender: Any, instance: FeatureFlag, raw: bool = False, **kwargs: Any) -> None:
        if not raw and instance.active and not instance.deleted:
            handler(instance.id, instance.team_id)

    post_save.connect(
        receiver,
        sender=FeatureFlag,
        weak=False,
        dispatch_uid=f"on_active_flag_saved:{handler.__module__}.{handler.__qualname__}",
    )
