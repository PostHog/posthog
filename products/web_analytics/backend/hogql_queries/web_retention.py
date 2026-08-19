from posthog.schema import ResolvedDateRangeResponse, RetentionQueryResponse

from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import is_precompute_enabled_for_team
from products.web_analytics.backend.hogql_queries.web_retention_lazy_precompute import (
    execute_lazy_precomputed_retention,
    is_retention_precompute_enabled_for_team,
)


class WebRetentionQueryRunner(RetentionQueryRunner):
    """Retention runner for queries originating from the web analytics product
    (routed by `tags.productKey` at dispatch). Serves the tile's weekly
    first-occurrence any-event shape from the web_retention precompute buckets
    and falls back to the standard retention path for everything else.
    Subclassing keeps the response contract and gives the result cache a
    distinct namespace (class name is part of the cache payload), so
    precompute-served results never collide with vanilla retention entries.
    """

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        # Rollout state in the cache key = immediate kill switch: disabling a
        # flag must not keep serving cached precompute-served results until
        # they stale out (same mechanism as WebTrendsQueryRunner).
        payload["web_retention_precompute"] = is_retention_precompute_enabled_for_team(
            self.team
        ) and is_precompute_enabled_for_team(self.team)
        return payload

    def _calculate(self) -> RetentionQueryResponse:
        results = execute_lazy_precomputed_retention(self)
        if results is None:
            return super()._calculate()

        return RetentionQueryResponse(
            results=results,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
