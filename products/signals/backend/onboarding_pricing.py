from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.event_usage import groups

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User


def onboarding_usage_based_pricing(team: Team, user: User | None) -> bool | None:
    try:
        value = posthoganalytics.feature_enabled(
            "self-driving-ubp",
            str(user.distinct_id if user else team.uuid),
            groups=groups(team=team),
            send_feature_flag_events=False,
        )
        return value if isinstance(value, bool) else None
    except Exception:
        return None
