from collections.abc import Callable
from typing import Any, NamedTuple

from products.error_tracking.backend.logic import effective_per_issue_rate_limit
from products.error_tracking.backend.models import ErrorTrackingSettings

from .base import Recommendation


class RateLimit(NamedTuple):
    key: str
    field: str
    # Answers "is this project's exception volume actually capped", which for the per-issue
    # limit includes the fallback teams get without configuring anything.
    in_effect: Callable[[int | None], bool]


RATE_LIMITS: list[RateLimit] = [
    RateLimit("project", "project_rate_limit_value", lambda value: value is not None and value > 0),
    RateLimit(
        "per_issue", "per_issue_rate_limit_value", lambda value: effective_per_issue_rate_limit(value) is not None
    ),
]


class RateLimitsRecommendation(Recommendation):
    type = "rate_limits"
    refresh_interval = None

    def is_completed(self, meta: dict[str, Any]) -> bool:
        rate_limits = meta.get("rate_limits") or []
        return bool(rate_limits) and all(r.get("enabled") for r in rate_limits)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        fields = [rate_limit.field for rate_limit in RATE_LIMITS]
        settings_by_team = {
            row["team_id"]: row
            for row in ErrorTrackingSettings.objects.filter(team_id__in=team_ids).values("team_id", *fields)
        }
        return {team_id: self._build_meta(settings_by_team.get(team_id)) for team_id in team_ids}

    @staticmethod
    def _build_meta(settings: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "rate_limits": [
                {
                    "key": rate_limit.key,
                    "enabled": rate_limit.in_effect((settings or {}).get(rate_limit.field)),
                }
                for rate_limit in RATE_LIMITS
            ]
        }
