from typing import Any

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

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        fields = [rate_limit["field"] for rate_limit in RATE_LIMITS]
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
                    "key": rate_limit["key"],
                    "enabled": settings is not None and settings.get(rate_limit["field"]) is not None,
                }
                for rate_limit in RATE_LIMITS
            ]
        }
