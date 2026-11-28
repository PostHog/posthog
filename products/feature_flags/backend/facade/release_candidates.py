from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.db.models.signals import post_save

from posthog.scopes.catalog import APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.feature_flags.backend.facade.config import is_v1_config
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


@dataclass(frozen=True)
class ReleaseFlagCondition:
    property_count: int
    # None when the condition stores no percentage, which serves everyone it matches.
    rollout_percentage: float | None
    variant: str | None
    aggregation_group_type_index: int | None


@dataclass(frozen=True)
class ReleaseFlagVariant:
    key: str
    rollout_percentage: float


@dataclass(frozen=True)
class ReleaseFlagState:
    """One flag as the release rules read it: its lifecycle and the parts of its config that decide its reach.

    `conditions` and `variants` are empty for a config that is not version 1, because the release rules read only
    version 1 rollouts.
    """

    id: int
    key: str
    name: str
    active: bool
    archived: bool
    created_at: datetime
    is_v1_config: bool
    aggregation_group_type_index: int | None
    conditions: tuple[ReleaseFlagCondition, ...]
    variants: tuple[ReleaseFlagVariant, ...]
    early_exit: bool
    feature_enrollment: bool
    holdout_exclusion_percentage: float


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _group_type(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _release_flag_state(flag: FeatureFlag) -> ReleaseFlagState:
    filters = flag.filters if isinstance(flag.filters, dict) else {}
    v1 = is_v1_config(flag.filters)
    groups = filters.get("groups") if v1 else None
    multivariate = filters.get("multivariate") if v1 else None
    variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
    holdout = filters.get("holdout")
    return ReleaseFlagState(
        id=flag.id,
        key=flag.key,
        name=flag.name or "",
        active=flag.active,
        archived=flag.archived,
        created_at=flag.created_at,
        is_v1_config=v1,
        aggregation_group_type_index=_group_type(filters.get("aggregation_group_type_index")),
        conditions=tuple(
            ReleaseFlagCondition(
                property_count=len(group.get("properties") or []),
                rollout_percentage=_number(group.get("rollout_percentage")),
                variant=group.get("variant") if isinstance(group.get("variant"), str) else None,
                aggregation_group_type_index=_group_type(group.get("aggregation_group_type_index")),
            )
            for group in (groups if isinstance(groups, list) else [])
            if isinstance(group, dict)
        ),
        variants=tuple(
            ReleaseFlagVariant(key=variant["key"], rollout_percentage=_number(variant.get("rollout_percentage")) or 0)
            for variant in (variants if isinstance(variants, list) else [])
            if isinstance(variant, dict) and isinstance(variant.get("key"), str)
        ),
        early_exit=bool(filters.get("early_exit")),
        feature_enrollment=bool(filters.get("feature_enrollment")),
        holdout_exclusion_percentage=(
            _number(holdout.get("exclusion_percentage")) or 0 if isinstance(holdout, dict) else 0
        ),
    )


def release_flag_states(
    *, team_id: int, flag_ids: list[int], access_control: UserAccessControl | None
) -> list[ReleaseFlagState]:
    """The flags of the team among `flag_ids` that are not deleted and that `access_control` lets the viewer see.

    A flag the viewer may not see is left out, so its key, name and config never reach the caller.
    """
    if not flag_ids:
        return []
    flags = _visible(
        FeatureFlag.objects.filter(team_id=team_id, id__in=flag_ids, deleted=False), access_control, "feature_flag"
    ).only("id", "key", "name", "active", "archived", "created_at", "filters", "team_id", "created_by_id")
    return [_release_flag_state(flag) for flag in flags.order_by("id")]


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
