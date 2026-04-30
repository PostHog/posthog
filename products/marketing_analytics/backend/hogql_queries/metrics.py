from prometheus_client import Counter

CONVERSION_GOAL_PRECOMPUTE_FALLBACK_COUNTER = Counter(
    "marketing_analytics_conversion_goal_precompute_fallback_total",
    "Conversion goal queries that fell back to the events scan after the precompute path raised",
)
