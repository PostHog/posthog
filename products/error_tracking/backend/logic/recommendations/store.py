from typing import Any
from uuid import UUID

from django.utils import timezone

from products.error_tracking.backend.logic.recommendations import RECOMMENDATIONS_BY_TYPE
from products.error_tracking.backend.logic.recommendations.refresh import claim_for_compute, revert_to_ready
from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.tasks import compute_error_tracking_recommendation


class RecommendationNotFoundError(Exception):
    pass


class UnknownRecommendationTypeError(Exception):
    pass


def list_recommendations(team_id: int) -> list[ErrorTrackingRecommendation]:
    return list(ErrorTrackingRecommendation.objects.filter(team_id=team_id).select_related("team").order_by("type"))


def _get(team_id: int, recommendation_id: UUID) -> ErrorTrackingRecommendation:
    try:
        return ErrorTrackingRecommendation.objects.select_related("team").get(team_id=team_id, id=recommendation_id)
    except ErrorTrackingRecommendation.DoesNotExist as err:
        raise RecommendationNotFoundError() from err


def refresh_recommendation(team_id: int, recommendation_id: UUID, *, force: bool) -> ErrorTrackingRecommendation:
    recommendation = _get(team_id, recommendation_id)
    if recommendation.type not in RECOMMENDATIONS_BY_TYPE:
        raise UnknownRecommendationTypeError(recommendation.type)
    if force and claim_for_compute(recommendation.id, team_id, timezone.now()):
        try:
            compute_error_tracking_recommendation.delay(str(recommendation.id), team_id)
        except Exception:
            revert_to_ready(recommendation.id, team_id)
            raise
        recommendation.refresh_from_db()
    return recommendation


def dismiss_recommendation(team_id: int, recommendation_id: UUID) -> ErrorTrackingRecommendation:
    recommendation = _get(team_id, recommendation_id)
    recommendation.dismissed_at = timezone.now()
    recommendation.save(update_fields=["dismissed_at", "updated_at"])
    return recommendation


def restore_recommendation(team_id: int, recommendation_id: UUID) -> ErrorTrackingRecommendation:
    recommendation = _get(team_id, recommendation_id)
    recommendation.dismissed_at = None
    recommendation.save(update_fields=["dismissed_at", "updated_at"])
    return recommendation


def enrich_meta(obj: ErrorTrackingRecommendation) -> dict[str, Any]:
    rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
    if not rec:
        return obj.meta
    return rec.enrich(obj.team, obj.meta)


def is_completed(obj: ErrorTrackingRecommendation, enriched_meta: dict[str, Any]) -> bool:
    # A recommendation that has never finished computing can't be considered completed,
    # even if its empty default meta would otherwise satisfy is_completed().
    if obj.computed_at is None:
        return False
    rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
    if not rec:
        return False
    return rec.is_completed(enriched_meta)
