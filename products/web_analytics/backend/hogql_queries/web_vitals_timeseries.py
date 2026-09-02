from typing import Any, cast

from posthog.schema import QueryTiming, ResolvedDateRangeResponse, TrendsQuery, TrendsQueryResponse, WebVitalsQuery

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.schema_helpers import to_dict

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import is_precompute_enabled_for_team
from products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute import (
    execute_lazy_precomputed_vitals_timeseries,
    is_vitals_precompute_enabled_for_team,
)


class WebVitalsQueryRunner(TrendsQueryRunner):
    """Runner for the Web Vitals tab query — a WebVitalsQuery wrapper whose
    `source` is a TrendsQuery of the four metric series. Without this runner
    the wrapper has no `get_query_runner` branch and `process_query_model`
    unwraps to the source, so dispatch only routes here when the vitals
    precompute flag is on; falling back preserves that exact live path.

    Serves the timeseries from the shared vitals-paths precompute buckets
    (the ones the path-breakdown tile on the same tab keeps warm) and falls
    back to the live trends path for everything else. Subclassing keeps the
    response contract; the class name gives the result cache a distinct
    namespace from vanilla trends entries.
    """

    def __init__(self, query: WebVitalsQuery | dict[str, Any], **kwargs: Any):
        vitals_query = query if isinstance(query, WebVitalsQuery) else WebVitalsQuery.model_validate(query)
        self.vitals_query = vitals_query
        source = vitals_query.source
        if not isinstance(source, TrendsQuery):
            # Dispatch only routes TrendsQuery-sourced wrappers here (non-Trends
            # sources fall through to the legacy source unwrap), so this guards
            # against direct/invalid construction, not the dispatch path.
            raise ValueError(f"WebVitalsQueryRunner requires a TrendsQuery source, got {type(source).__name__}")
        super().__init__(query=source, **kwargs)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        # Rollout state in the cache key = immediate kill switch: disabling a
        # flag must not keep serving cached precompute-derived results until
        # they stale out (same mechanism as WebTrendsQueryRunner).
        payload["web_vitals_timeseries_precompute"] = is_vitals_precompute_enabled_for_team(
            self.team
        ) and is_precompute_enabled_for_team(self.team)
        # `super()` serializes only the inner TrendsQuery, but the precompute
        # read builds its jobs from the wrapper's own filters (see
        # `_build_inner_path_breakdown_query`). Fold those into the key — using
        # the base payload's normalization — so two wrappers that share a source
        # but differ in outer filters can't collide.
        wrapper = to_dict(self.vitals_query)
        payload["web_vitals_wrapper_properties"] = wrapper.get("properties")
        payload["web_vitals_wrapper_do_path_cleaning"] = wrapper.get("doPathCleaning")
        return payload

    def enqueue_async_calculation(self, *args: Any, **kwargs: Any) -> Any:
        # The async payload is `self.query.model_dump()`, which here is the
        # bare source; a worker rebuilding from that would run plain trends
        # under this runner's cache key. Serialize the wrapper instead so
        # dispatch routes the worker back to this runner.
        original = self.query
        # Deliberate type lie for the duration of the enqueue: the base method
        # only calls model_dump() on it, and the worker validates the payload
        # back into a WebVitalsQuery at dispatch.
        self.query = cast(TrendsQuery, self.vitals_query)
        try:
            return super().enqueue_async_calculation(*args, **kwargs)
        finally:
            self.query = original

    def _calculate(self) -> TrendsQueryResponse:
        results = execute_lazy_precomputed_vitals_timeseries(self)
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
        )
