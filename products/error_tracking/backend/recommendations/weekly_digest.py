from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import NOTIFICATION_DEFAULTS, User

from .base import Recommendation


def _digest_enabled_for_user_and_team(user: User, team: Team) -> bool:
    """Whether the error tracking weekly digest is configured for this user+team.

    We only consider error-tracking-specific settings — the global
    `all_weekly_digest_disabled` kill-switch is ignored on purpose so this
    recommendation stays scoped to the product the user is looking at.

    Enabled requires:
      - `error_tracking_weekly_digest` is not False (ET digest on)
      - The user has explicitly opted this team in via
        `error_tracking_weekly_digest_project_enabled[team_id] == True`.
        (We treat "not configured" as not enabled — the auto-select picks one
        project on first digest run, so the user is only reliably included once
        they select the team themselves.)
    """
    settings = user.notification_settings
    if not settings.get(
        "error_tracking_weekly_digest", NOTIFICATION_DEFAULTS.get("error_tracking_weekly_digest", True)
    ):
        return False
    per_project = settings.get("error_tracking_weekly_digest_project_enabled") or {}
    return bool(per_project.get(str(team.id)))


class WeeklyDigestRecommendation(Recommendation):
    type = "weekly_digest"
    # Very short cooldown — meta is trivially cheap to compute (just reads the
    # user's notification_settings JSON) and we want the card to react quickly
    # when the user toggles settings elsewhere.
    refresh_interval = timedelta(seconds=5)
    user_scoped = True

    def compute(self, team: Team, user: User | None = None) -> dict[str, Any]:
        if user is None:
            return {"enabled": False}
        return {"enabled": _digest_enabled_for_user_and_team(user, team)}
