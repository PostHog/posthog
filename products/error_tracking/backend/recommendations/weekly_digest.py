from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import NOTIFICATION_DEFAULTS, User

from .base import Recommendation


def _digest_enabled_for_user_and_team(user: User, team: Team) -> bool:
    settings = user.notification_settings
    if not settings.get(
        "error_tracking_weekly_digest", NOTIFICATION_DEFAULTS.get("error_tracking_weekly_digest", True)
    ):
        return False
    per_project = settings.get("error_tracking_weekly_digest_project_enabled") or {}
    return bool(per_project.get(str(team.id)))


class WeeklyDigestRecommendation(Recommendation):
    type = "weekly_digest"
    refresh_interval = timedelta(seconds=5)
    user_scoped = True

    def compute(self, team: Team, user: User | None = None) -> dict[str, Any]:
        if user is None:
            return {"enabled": False}
        return {"enabled": _digest_enabled_for_user_and_team(user, team)}
