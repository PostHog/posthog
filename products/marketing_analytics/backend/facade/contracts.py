from posthog.schema import MarketingAnalyticsCostSource, TrendsQuery

from posthog.dataclasses import frozen


@frozen
class ResolvedMarketingCostTrend:
    query: TrendsQuery
    # None when an edited insight no longer reads the cost table, so neither path applies.
    source: MarketingAnalyticsCostSource | None
