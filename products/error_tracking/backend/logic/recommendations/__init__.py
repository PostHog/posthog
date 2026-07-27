from .alerts import AlertsRecommendation
from .base import Recommendation
from .long_running_issues import LongRunningIssuesRecommendation
from .rate_limits import RateLimitsRecommendation
from .source_maps import SourceMapsRecommendation

# Each type and its meta payload is documented for the MCP agent in
# products/error_tracking/mcp/prompts/error-tracking-recommendations-list.md — keep it in sync when adding/changing a type.
RECOMMENDATIONS: list[Recommendation] = [
    AlertsRecommendation(),
    LongRunningIssuesRecommendation(),
    RateLimitsRecommendation(),
    SourceMapsRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
