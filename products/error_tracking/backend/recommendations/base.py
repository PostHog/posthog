from abc import ABC, abstractmethod
from typing import Any, ClassVar

from posthog.models.team.team import Team


class BaseRecommendation(ABC):
    """
    Base class for an error tracking recommendation.

    Each subclass owns the full lifecycle of a single recommendation type:
    - what data to compute (`compute`)
    - which Team fields should cause the recommendation to be recomputed
      when they change (`watched_team_fields`)

    Recommendations are materialized into `ErrorTrackingRecommendationRun` rows
    via the celery task `run_error_tracking_recommendation` so the frontend can
    load them without doing any work on the request path.
    """

    # A unique key for this recommendation type. Must match one of the
    # ErrorTrackingRecommendationRun.Type choices.
    type: ClassVar[str]

    # Team fields whose changes should invalidate this recommendation. Empty by
    # default so recommendations that don't depend on Team config don't get
    # recomputed on every team save.
    watched_team_fields: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    @abstractmethod
    def compute(cls, team: Team) -> dict[str, Any]:
        """Return the `meta` JSON payload for the recommendation row."""
        raise NotImplementedError
