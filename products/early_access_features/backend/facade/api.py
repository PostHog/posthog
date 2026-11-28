"""Facade for early access features. The only module other products may import from this product.

The contract types live here rather than in `contracts.py`, because a `contracts.py` puts the product under the
strict `product:lint` layout, which asks for a tsconfig.json and the API views under `backend/presentation/`.
"""

from datetime import datetime
from uuid import UUID

from django.db.models import Q, QuerySet

from pydantic.dataclasses import dataclass

from products.early_access_features.backend.models import EarlyAccessFeature


@dataclass(frozen=True)
class FlagEarlyAccessFeature:
    id: UUID
    name: str
    # The stored stage: draft, concept, alpha, beta, general-availability or archived.
    stage: str
    created_at: datetime
    feature_flag_id: int


@dataclass(frozen=True)
class FlagEarlyAccessFeatures:
    """The early access features of some flags that the viewer may see.

    `hidden_flag_ids` names the flags that also have a feature the viewer may not see, so a caller knows its view of
    those flags is incomplete without learning anything about the hidden feature.
    """

    features: tuple[FlagEarlyAccessFeature, ...]
    hidden_flag_ids: frozenset[int]


@dataclass(frozen=True)
class EarlyAccessListAccess:
    """Which early access features the access control rules let a list show the viewer.

    This is the narrowing that `UserAccessControl.filter_queryset_by_access_level` applies. With `only_allowed`, the
    viewer has no resource-level access: the list keeps the allowed ids and the viewer's own features. Otherwise it
    drops the blocked ids, except the viewer's own features.
    """

    viewer_id: int
    only_allowed: bool
    allowed_ids: frozenset[str]
    blocked_ids: frozenset[str]


def _visible_to(features: QuerySet[EarlyAccessFeature], access: EarlyAccessListAccess) -> QuerySet[EarlyAccessFeature]:
    own = Q(created_by_id=access.viewer_id)
    if access.only_allowed:
        return features.filter(Q(id__in=access.allowed_ids) | own)
    if access.blocked_ids:
        return features.exclude(Q(id__in=access.blocked_ids) & ~own)
    return features


def early_access_features_for_flags(
    *, team_id: int, flag_ids: list[int], access: EarlyAccessListAccess | None
) -> FlagEarlyAccessFeatures:
    """The team's early access features on `flag_ids` that `access` lets the viewer see, oldest first.

    With no `access`, every feature counts as visible.
    """
    if not flag_ids:
        return FlagEarlyAccessFeatures(features=(), hidden_flag_ids=frozenset())
    features = EarlyAccessFeature.objects.filter(team_id=team_id, feature_flag_id__in=flag_ids)
    visible = features if access is None else _visible_to(features, access)
    shown = [
        FlagEarlyAccessFeature(
            id=feature_id, name=name, stage=stage, created_at=created_at, feature_flag_id=feature_flag_id
        )
        for feature_id, name, stage, created_at, feature_flag_id in visible.order_by("created_at", "id").values_list(
            "id", "name", "stage", "created_at", "feature_flag_id"
        )
    ]
    shown_ids = {feature.id for feature in shown}
    return FlagEarlyAccessFeatures(
        features=tuple(shown),
        hidden_flag_ids=frozenset(
            feature_flag_id
            for feature_id, feature_flag_id in features.values_list("id", "feature_flag_id")
            if feature_id not in shown_ids
        ),
    )
