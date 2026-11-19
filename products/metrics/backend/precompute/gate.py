"""Which projects precompute metrics.

Phase 1 stores precomputed metrics in Postgres, which is sized for one project. On PostHog Cloud they run only
for the allowlisted projects, and everywhere only with dashboard-v2. Phase 2 moves storage to ClickHouse before
any second project.
"""

from posthog.models import Team
from posthog.permissions import posthog_feature_flag_enabled
from posthog.utils import get_instance_region

DASHBOARD_V2_FEATURE_FLAG = "dashboard-v2"
_CLOUD_TEAM_IDS: dict[str, frozenset[int]] = {"US": frozenset({2})}


def precompute_enabled(team: Team) -> bool:
    region = get_instance_region()
    if region in ("US", "EU") and team.pk not in _CLOUD_TEAM_IDS.get(region, frozenset()):
        return False
    # `dashboard-v2` is aggregated by project, so the distinct id doesn't decide it.
    return posthog_feature_flag_enabled(
        DASHBOARD_V2_FEATURE_FLAG,
        str(team.uuid),
        organization_id=team.organization_id,
        team_id=team.pk,
        only_evaluate_locally=True,
    )
