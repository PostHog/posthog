from .alerts import AlertsRecommendation
from .base import Recommendation
from .issue_summaries import IssueSummariesRecommendation
from .rate_limits import RateLimitsRecommendation
from .source_maps import SourceMapsRecommendation

# Each type and its meta payload is documented for the MCP agent in
# products/error_tracking/mcp/prompts/error-tracking-recommendations-list.md — keep it in sync when adding/changing a type.
RECOMMENDATIONS: list[Recommendation] = [
    AlertsRecommendation(),
    # Not in the MCP doc. Every MCP user reads that doc, and summaries must stay unknown outside their feature flag.
    IssueSummariesRecommendation(),
    RateLimitsRecommendation(),
    SourceMapsRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
