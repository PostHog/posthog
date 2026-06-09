from typing import Any

from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingSettings

from .base import Recommendation

RATE_LIMITS: list[dict[str, str]] = [
    {"key": "project", "field": "project_rate_limit_value"},
    {"key": "per_issue", "field": "per_issue_rate_limit_value"},
]


class RateLimitsRecommendation(Recommendation):
    type = "rate_limits"
    refresh_interval = None

    def is_completed(self, meta: dict[str, Any]) -> bool:
        rate_limits = meta.get("rate_limits") or []
        return bool(rate_limits) and all(r.get("enabled") for r in rate_limits)

    def compute(self, team: Team) -> dict[str, Any]:
        settings = ErrorTrackingSettings.objects.filter(team_id=team.id).first()

        return {
            "rate_limits": [
                {
                    "key": rate_limit["key"],
                    "enabled": settings is not None and getattr(settings, rate_limit["field"]) is not None,
                }
                for rate_limit in RATE_LIMITS
            ]
        }
