from typing import TYPE_CHECKING, Optional

from posthog.cloud_utils import is_cloud

from products.web_analytics.backend.hogql_queries.first_pageview_flag import evaluate_team_rollout_flag

if TYPE_CHECKING:
    from posthog.models import Team

COOKIELESS_TRAFFIC_IS_REGULAR_FEATURE_FLAG = "cookieless-traffic-is-regular"


def resolve_cookieless_traffic_is_regular_modifier(team: "Team", current: Optional[bool]) -> Optional[bool]:
    if current is not None:
        return current
    if not is_cloud():
        return None
    if not evaluate_team_rollout_flag(
        team,
        COOKIELESS_TRAFFIC_IS_REGULAR_FEATURE_FLAG,
        "cookieless_traffic_is_regular_flag_failed",
        log_unresolved=False,
    ):
        return None
    return True
