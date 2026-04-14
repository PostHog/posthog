from products.error_tracking.backend.temporal.activities import (
    compute_recommendation_activity,
    get_stale_recommendations_activity,
)
from products.error_tracking.backend.temporal.workflows import RecommendationsCoordinatorWorkflow

WORKFLOWS: list = [RecommendationsCoordinatorWorkflow]
ACTIVITIES: list = [get_stale_recommendations_activity, compute_recommendation_activity]

__all__ = [
    "RecommendationsCoordinatorWorkflow",
    "get_stale_recommendations_activity",
    "compute_recommendation_activity",
    "WORKFLOWS",
    "ACTIVITIES",
]
