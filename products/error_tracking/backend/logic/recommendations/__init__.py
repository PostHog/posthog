from posthog.models.team.team import Team

from .alerts import AlertsRecommendation
from .audience_slices import AudienceSlicesRecommendation
from .base import Recommendation
from .fires_on_leave import FiresOnLeaveRecommendation
from .flow_drop import FlowDropRecommendation
from .funnel_step import FunnelStepRecommendation
from .impact_lens import ImpactLens, impact_enabled
from .inflated_counts import InflatedCountsRecommendation
from .known_patterns import KnownPatternsRecommendation
from .long_running_issues import LongRunningIssuesRecommendation
from .lost_visitor import LostVisitorRecommendation
from .many_accounts import ManyAccountsRecommendation
from .one_account import OneAccountRecommendation
from .quick_leave import QuickLeaveRecommendation
from .rate_limits import RateLimitsRecommendation
from .related_issues import RelatedIssuesRecommendation
from .source_maps import SourceMapsRecommendation
from .support_tickets import SupportTicketsRecommendation
from .suppressed_events import SuppressedEventsRecommendation

# Each type and its meta payload is documented for the MCP agent in
# products/error_tracking/mcp/prompts/error-tracking-recommendations-list.md — keep it in sync when adding/changing a type.
RECOMMENDATIONS: list[Recommendation] = [
    AlertsRecommendation(),
    AudienceSlicesRecommendation(),
    FiresOnLeaveRecommendation(),
    FlowDropRecommendation(),
    FunnelStepRecommendation(),
    InflatedCountsRecommendation(),
    KnownPatternsRecommendation(),
    LongRunningIssuesRecommendation(),
    LostVisitorRecommendation(),
    ManyAccountsRecommendation(),
    OneAccountRecommendation(),
    QuickLeaveRecommendation(),
    RateLimitsRecommendation(),
    RelatedIssuesRecommendation(),
    SourceMapsRecommendation(),
    SupportTicketsRecommendation(),
    SuppressedEventsRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}


def enabled_recommendations(team: Team) -> list[Recommendation]:
    """The recommendations that run for a team. The impact flag is evaluated once for all of the impact lenses."""
    impact = impact_enabled(team)
    return [
        rec for rec in RECOMMENDATIONS if (impact if isinstance(rec, ImpactLens) else rec.is_enabled_for_team(team))
    ]
