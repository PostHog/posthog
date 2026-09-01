from posthog.schema import QueryTiming, ResolvedDateRangeResponse, TrendsQueryResponse

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    is_precompute_enabled_for_team,
    is_team_above_volume_floor,
)
from products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute import (
    execute_lazy_precomputed_trends,
    is_trends_precompute_enabled_for_team,
)


class WebTrendsQueryRunner(TrendsQueryRunner):
    """Trends runner for queries originating from the web analytics product
    (routed by `tags.productKey` at dispatch). Serves eligible single-series
    shapes from the shared web_overview precompute buckets — the same buckets
    the overview tile keeps warm — and falls back to the standard trends path
    for everything else. Subclassing keeps the response contract and gives the
    HogQL result cache a distinct namespace (class name is part of the cache
    payload), so precompute-served results never collide with vanilla trends
    cache entries.
    """

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        # Fold rollout state into the cache key so disabling either flag is an
        # immediate kill switch: without this, cached precompute-served results
        # keep being returned until they stale out naturally (the overview
        # runner does the same via its `_pc` cache-key suffix).
        precompute = is_trends_precompute_enabled_for_team(self.team) and is_precompute_enabled_for_team(self.team)
        payload["web_trends_precompute"] = precompute
        # The volume floor also flips the serving path (precompute <-> live), so
        # it must vary the key too: a team crossing below the floor keeps serving
        # a stale precompute result otherwise. Read it only when precompute is on.
        payload["web_trends_above_floor"] = precompute and is_team_above_volume_floor(self.team.pk)
        return payload

    def _calculate(self) -> TrendsQueryResponse:
        results = execute_lazy_precomputed_trends(self)
        if results is None:
            return super()._calculate()

        timings: list[QueryTiming] = self.timings.to_list()
        return TrendsQueryResponse(
            results=results,
            hasMore=False,
            timings=timings,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
            resolved_compare_date_range=ResolvedDateRangeResponse(
                date_from=self.query_previous_date_range.date_from(),
                date_to=self.query_previous_date_range.date_to(),
            )
            if self.query.compareFilter is not None and self.query.compareFilter.compare
            else None,
        )
