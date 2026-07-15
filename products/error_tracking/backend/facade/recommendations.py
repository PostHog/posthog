"""Facade for error tracking recommendations.

Kept separate from ``facade/api.py`` so the recommendation compute modules' heavy
imports (ClickHouse, cross-product models) stay off the django.setup() path of
config-only consumers of the main facade.
"""

from uuid import UUID

from ..logic.recommendations import (
    refresh as _refresh,
    store as _store,
)
from . import contracts

RecommendationNotFoundError = _store.RecommendationNotFoundError
UnknownRecommendationTypeError = _store.UnknownRecommendationTypeError
RecommendationRefreshUnavailableError = _store.RecommendationRefreshUnavailableError


def _to_recommendation(obj) -> contracts.ErrorTrackingRecommendation:
    enriched = _store.enrich_meta(obj)
    return contracts.ErrorTrackingRecommendation(
        id=obj.id,
        type=obj.type,
        meta=enriched,
        completed=_store.is_completed(obj, enriched),
        status=obj.status,
        computed_at=obj.computed_at,
        dismissed_at=obj.dismissed_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def refresh_team_recommendations(team_id: int) -> int:
    return _refresh.refresh_team_recommendations(team_id)


def list_recommendations(team_id: int) -> list[contracts.ErrorTrackingRecommendation]:
    return [_to_recommendation(obj) for obj in _store.list_recommendations(team_id)]


def refresh_recommendation(
    team_id: int, recommendation_id: UUID, *, force: bool
) -> contracts.ErrorTrackingRecommendation:
    return _to_recommendation(_store.refresh_recommendation(team_id, recommendation_id, force=force))


def dismiss_recommendation(team_id: int, recommendation_id: UUID) -> contracts.ErrorTrackingRecommendation:
    return _to_recommendation(_store.dismiss_recommendation(team_id, recommendation_id))


def restore_recommendation(team_id: int, recommendation_id: UUID) -> contracts.ErrorTrackingRecommendation:
    return _to_recommendation(_store.restore_recommendation(team_id, recommendation_id))
