from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.permissions import _FORCE_ENABLED_FLAGS

from products.pulse.backend.config import PULSE_EXPANSION_FLAG

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


def pulse_expansion_enabled(*, team: Team, user: User) -> bool:
    """Match in-app flag evaluation: user distinct_id plus project/org groups."""
    if PULSE_EXPANSION_FLAG in _FORCE_ENABLED_FLAGS:
        return True

    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    return bool(
        posthoganalytics.feature_enabled(
            PULSE_EXPANSION_FLAG,
            distinct_id,
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )
