from prometheus_client import Counter

CONVERSION_GOAL_PRECOMPUTE_FALLBACK_COUNTER = Counter(
    "marketing_analytics_conversion_goal_precompute_fallback_total",
    "Conversion goal queries that fell back to the events scan after the precompute path raised",
)

# Labeled by reason, following the web analytics convention, because the reasons carry very different
# weight: `custom_channel_rules` and `non_integer_timezone` are permanent for a team (they will never
# use this path), `not_ready` is transient warm-up, and `exception` is a bug. An unlabeled counter
# would blur "this team is ineligible forever" into "the cache was cold once".
ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER = Counter(
    "marketing_analytics_attribution_reach_precompute_fallback_total",
    "Attribution reach queries that fell back to the live pageview scan",
    ["reason"],
)

ATTRIBUTION_REACH_PRECOMPUTE_SUCCESS_COUNTER = Counter(
    "marketing_analytics_attribution_reach_precompute_success_total",
    "Attribution reach queries served from the pre-aggregated table",
)
