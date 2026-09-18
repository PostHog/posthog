"""The rollout gate for targeting realtime cohorts from feature flags.

Its own module because both API modules read it and they import each other: the feature flag API
imports `CohortSerializer` from `posthog.api.cohort`, so the cohort API cannot import the flag API
back at module level. A module neither of them imports lets both reach the gate normally.
"""

from typing import Any

from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

REALTIME_COHORT_FLAG_TARGETING_FLAG = "realtime-cohort-flag-targeting"


def is_realtime_cohort_flag_targeting_enabled(request: Any, *, team: Team) -> bool:
    """Whether this request's user is in the realtime cohort flag targeting rollout.

    Cloud evaluates the flag locally in the common case, but this is allowed to fall back to a
    remote call, so callers ask only about cohorts the answer could change something for.
    """
    try:
        user = getattr(request, "user", None)
        if user is None or user.is_anonymous:
            return False
        organization_id = str(team.organization_id)
        return feature_enabled_or_false(
            REALTIME_COHORT_FLAG_TARGETING_FLAG,
            user.distinct_id,
            groups={"organization": organization_id, "project": str(team.uuid)},
            group_properties={"organization": {"id": organization_id}, "project": {"id": team.id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        return False
