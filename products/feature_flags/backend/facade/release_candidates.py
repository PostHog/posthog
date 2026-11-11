from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db.models import Prefetch, Q, QuerySet
from django.db.models.signals import post_save

from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey


@dataclass(frozen=True)
class LinkedName:
    id: str
    name: str


@dataclass(frozen=True)
class ReleaseImportFlag:
    id: int
    key: str
    created_at: datetime
    created_by_id: int | None
    experiments: tuple[LinkedName, ...]
    early_access: tuple[LinkedName, ...]


def _visible(
    queryset: QuerySet, access_control: UserAccessControl | None, resource: APIScopeObject | None = None
) -> QuerySet:
    if access_control is None:
        return queryset
    return access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True, resource=resource)


def list_release_import_flags(
    *,
    team_id: int,
    project_id: int,
    access_control: UserAccessControl | None,
    flag_ids: list[int] | None = None,
) -> list[ReleaseImportFlag]:
    experiment_model = FeatureFlag.experiment_set.rel.related_model
    early_access_model = FeatureFlag.features.rel.related_model
    experiments = _visible(
        experiment_model._default_manager.filter(deleted=False, archived=False).only("id", "name", "feature_flag_id"),
        access_control,
        "experiment",
    ).order_by("created_at", "id")
    early_access = (
        _visible(
            early_access_model._default_manager.exclude(stage="archived").only("id", "name", "feature_flag_id"),
            access_control,
            "early_access_feature",
        )
        .filter(feature_flag__isnull=False)
        .order_by("created_at", "id")
    )
    # nosemgrep: environment-model-scoped-by-project
    tour_flag_ids = ProductTour.all_objects.filter(
        team__project_id=project_id, internal_targeting_flag__isnull=False
    ).values_list("internal_targeting_flag_id", flat=True)
    candidates = FeatureFlag.objects.filter(team_id=team_id, deleted=False, archived=False, active=True)
    if flag_ids is not None:
        candidates = candidates.filter(id__in=flag_ids)
    flags = (
        _visible(
            candidates.exclude(is_remote_configuration=True).exclude(
                Q(id__in=Survey.get_internal_flag_ids(project_id=project_id)) | Q(id__in=tour_flag_ids)
            ),
            access_control,
        )
        .only("id", "key", "created_at", "created_by_id")
        .prefetch_related(
            Prefetch("experiment_set", queryset=experiments, to_attr="release_experiments"),
            Prefetch("features", queryset=early_access, to_attr="release_early_access"),
        )
        .order_by("created_at", "id")
    )
    return [
        ReleaseImportFlag(
            id=flag.id,
            key=flag.key,
            created_at=flag.created_at,
            created_by_id=flag.created_by_id,
            experiments=tuple(LinkedName(id=str(item.id), name=item.name) for item in flag.release_experiments),
            early_access=tuple(LinkedName(id=str(item.id), name=item.name) for item in flag.release_early_access),
        )
        for flag in flags
    ]


def on_flag_created(handler: Callable[[int, int], None]) -> None:
    def receiver(sender: Any, instance: FeatureFlag, created: bool, raw: bool = False, **kwargs: Any) -> None:
        if created and not raw:
            handler(instance.id, instance.team_id)

    post_save.connect(
        receiver,
        sender=FeatureFlag,
        weak=False,
        dispatch_uid=f"on_flag_created:{handler.__module__}.{handler.__qualname__}",
    )
