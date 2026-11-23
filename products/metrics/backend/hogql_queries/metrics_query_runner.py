"""Runner for the `MetricsQuery` schema node (insights, dashboards, /query).

A thin translation layer: schema `MetricsQuery` -> facade `MetricQueryRequest`
-> `run_metric_query` -> schema `MetricsQuerySeries`. The single-clause HogQL
engine lives in `metric_query_runner.py` (singular); this runner never
bypasses the facade, so the viewer, MCP tools, and insights all share one
query path.
"""

from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import datetime
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any, Optional, cast

from posthog.schema import (
    CachedMetricsQueryResponse,
    DashboardFilter,
    DateRange,
    MetricsDashboardVariable,
    MetricsDashboardVariableSource,
    MetricsQuery,
    MetricsQueryLanguage,
    MetricsQueryPoint,
    MetricsQueryProvenance,
    MetricsQueryResponse,
    MetricsQuerySeries,
)

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.clickhouse.client.limit import QueryLane
from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.permissions import posthog_feature_flag_enabled
from posthog.shared_link_user import SharedLinkUser

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.metrics.backend.dashboard_import.promql_text import drop_match_all_matchers
from products.metrics.backend.date_range import metrics_query_date_range
from products.metrics.backend.facade.api import (
    derived_metric_resources,
    run_metric_query,
    run_planned_metric_query,
    run_precomputed_promql_query,
)
from products.metrics.backend.facade.contracts import (
    DERIVED_SOURCE_QUERY_STATUS_LABEL_PREFIX,
    METRICS_FEATURE_FLAG,
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryProvenance as MetricQueryProvenanceContract,
    MetricQueryRequest,
    MetricQueryResult,
    MetricQueryShadowCheck,
    MetricSeries,
)
from products.metrics.backend.facade.enums import (
    AttributeScope,
    FilterOp,
    MetricAggregation,
    MetricQueryProvenanceMode,
    MetricRangeFunction,
    MetricType,
)
from products.metrics.backend.hogql_queries.tail_refresh import (
    TailRefresh,
    TailRefreshMixin,
    clause_at_cap,
    compare_series,
    merge_series,
)
from products.metrics.backend.metric_query_runner import _resolve_interval
from products.metrics.backend.precompute.gate import precompute_enabled
from products.metrics.backend.promql import run_promql_range
from products.metrics.backend.query_concurrency import query_concurrency_slots
from products.metrics.backend.query_interval import resolve_query_interval
from products.metrics.backend.sql_mode import run_metrics_sql
from products.metrics.backend.variable_options import fill_all_values
from products.metrics.backend.variables import (
    Variable,
    all_definitions,
    filter_referenced_names,
    from_dashboard,
    from_query,
    query_definitions,
    referenced_names,
    sql_referenced_names,
    substitute_filters,
    substitute_promql,
    substitute_sql,
    to_query,
    unresolved_message,
)

if TYPE_CHECKING:
    from posthog.models import User

DASHBOARD_V2_FEATURE_FLAG = "dashboard-v2"
# `query executed` reports a tile answered wholly from stored buckets as `derived`, the value that the precompute
# measurement queries filter on.
_EVENT_PROVENANCE = {
    MetricQueryProvenanceMode.PRECOMPUTED: "derived",
    MetricQueryProvenanceMode.MIXED: "mixed",
    MetricQueryProvenanceMode.RAW: "raw",
}


class MetricsQueryRunner(TailRefreshMixin, AnalyticsQueryRunner[MetricsQueryResponse]):
    query: MetricsQuery
    cached_response: CachedMetricsQueryResponse
    _loaded_variables: dict[str, Variable] | None = None
    _tile_dashboard_id: int | None = None
    _provenance: MetricQueryProvenanceContract | None = None
    _shadow: MetricQueryShadowCheck | None = None

    def validate_query_runner_access(self, user: "User") -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        user_access_control.assert_access_level_for_resource("metrics", "viewer")
        # A derived metric reads spans or logs, so the user needs access to that source too.
        for resource in derived_metric_resources(clause.metricName for clause in self.query.clauses):
            user_access_control.assert_access_level_for_resource(resource, "viewer")
        # Private alpha: RBAC alone isn't enough — mirror MetricsViewSet's flag gate here,
        # or POST /query with a MetricsQuery bypasses it.
        if not posthog_feature_flag_enabled(
            METRICS_FEATURE_FLAG,
            str(user.distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise UserAccessControlError("metrics", "viewer")
        # PromQL runs through Snuffle, which has its own private-alpha flag.
        if self._sends_promql() and not posthog_feature_flag_enabled(
            SNUFFLE_API_FEATURE_FLAG,
            str(user.distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise UserAccessControlError("metrics", "viewer")
        return True

    def query_status_labels(self) -> list[str] | None:
        # Retrieving an async result skips validate_query_runner_access, so the status carries the sources to check.
        resources = derived_metric_resources(clause.metricName for clause in self.query.clauses)
        return [f"{DERIVED_SOURCE_QUERY_STATUS_LABEL_PREFIX}{resource}" for resource in resources] or None

    def _enforce_alpha_gates_without_a_request_user(self) -> None:
        # Shared-link renders execute with an anonymous SharedLinkUser, and userless runs (scheduled
        # refreshes, cache warming) have no user. Both skip validate_query_runner_access (the share
        # link is the authorization), so the alpha flag gates must also hold here.
        # user is typed Optional[User] but runtime also passes SharedLinkUser (shared
        # renders); broaden for is_anonymous.
        user = cast("Optional[User | SharedLinkUser]", self.user)
        if user is not None and not user.is_anonymous:
            return
        distinct_id = str(getattr(user, "distinct_id", None) or f"shared-viewer-{self.team.pk}")
        # Userless runs pass the metrics gate: they only ever refresh insights of teams with the flag.
        if user is not None and not posthog_feature_flag_enabled(
            METRICS_FEATURE_FLAG,
            distinct_id,
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise UserAccessControlError("metrics", "viewer")
        # A team can have metrics without Snuffle, so a PromQL insight checks the Snuffle flag on every run.
        if self._sends_promql() and not posthog_feature_flag_enabled(
            SNUFFLE_API_FEATURE_FLAG,
            distinct_id,
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise UserAccessControlError("metrics", "viewer")

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise NotImplementedError(
            "MetricsQuery composes one HogQL query per clause via the metrics facade; there is no single statement"
        )

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        # `display` is presentation only — `_to_request` never reads it, so it must not namespace
        # the cache. Without this, adding a goal line re-runs every bucket in ClickHouse, and two
        # tiles differing only in chart type would each hold their own entry.
        payload["query"].pop("display", None)
        return payload

    def _to_request(self) -> MetricQueryRequest:
        date_range = self._date_range
        clauses = tuple(
            MetricQueryClause(
                name=clause.name,
                metric_name=clause.metricName,
                aggregation=MetricAggregation(clause.aggregation.value if clause.aggregation else "none"),
                range_function=MetricRangeFunction(clause.rangeFunction.value) if clause.rangeFunction else None,
                metric_type=MetricType(clause.metricType.value) if clause.metricType is not None else None,
                filters=tuple(
                    MetricFilter(
                        key=f.key,
                        op=FilterOp(f.op.value),
                        value=f.value,
                        scope=AttributeScope(f.scope.value) if f.scope is not None else AttributeScope.AUTO,
                    )
                    for f in clause.filters or []
                ),
                group_by=tuple(
                    MetricGroupBy(
                        key=g.key,
                        scope=AttributeScope(g.scope.value) if g.scope is not None else AttributeScope.AUTO,
                    )
                    for g in clause.groupBy or []
                ),
                quantile=clause.quantile,
                apdex_threshold_ms=clause.apdexThresholdMs,
            )
            for clause in self.query.clauses
        )
        return MetricQueryRequest(
            clauses=clauses,
            date_from=self._date_from,
            date_to=date_range.date_to(),
            interval=resolve_query_interval(
                self.query.interval, from_query(self.query.variables), self._date_from, date_range.date_to()
            ),
            formula=self.query.formula,
        )

    def _builder_request(self) -> MetricQueryRequest:
        variables = from_query(self.query.variables)
        clauses = []
        for clause in self.query.clauses:
            substitution = substitute_filters(clause.filters, variables)
            if substitution.unresolved:
                raise ValueError(unresolved_message(substitution.unresolved))
            clauses.append(clause.model_copy(update={"filters": substitution.filters}) if clause.filters else clause)
        self.query.clauses = clauses
        return self._to_request()

    def _run(self) -> list[MetricSeries]:
        language = self.query.language or MetricsQueryLanguage.BUILDER
        variables = from_query(self.query.variables)
        if language == MetricsQueryLanguage.BUILDER:
            return run_metric_query(team=self.team, request=self._builder_request())
        date_from, date_to = self._date_from, self._date_range.date_to()
        interval = resolve_query_interval(self.query.interval, variables, date_from, date_to)
        if language == MetricsQueryLanguage.PROMQL:
            if not (self.query.promql or "").strip():
                raise ValueError("Write a PromQL query first.")
            promql = substitute_promql(self.query.promql or "", variables)
            if promql.unresolved:
                raise ValueError(unresolved_message(promql.unresolved))
            # A variable set to All writes `label=~".*"`, which matches every series.
            text = drop_match_all_matchers(promql.text) if promql.text != self.query.promql else promql.text
            if self._tile_dashboard_id is not None and self._precompute_enabled:
                return self._keep_precompute(
                    run_precomputed_promql_query(
                        team=self.team,
                        promql=text,
                        date_from=date_from,
                        date_to=date_to,
                        interval=interval,
                        record_use=self._viewer_is_member,
                    )
                )
            return run_promql_range(self.team, text, date_from, date_to, interval)
        if not (self.query.sql or "").strip():
            raise ValueError("Write a SQL query first.")
        sql = substitute_sql(self.query.sql or "", self._load_all_options())
        if sql.unresolved:
            raise ValueError(unresolved_message(sql.unresolved))
        return run_metrics_sql(self.team, sql.sql, date_from, date_to, interval, sql.placeholders)

    def _call_with_rate_limits(self, *, dashboard_id: int | None) -> tuple[MetricsQueryResponse, float]:
        self._tile_dashboard_id = dashboard_id
        # Tiles that wait for one shared load of the All options must not hold the runner's concurrency slots.
        if get_query_tag_value("api_queries_budgeted"):
            self._enforce_api_queries_budget()
        try:
            self._load_all_options(dashboard_id)
        except ValueError as exc:
            raise ExposedHogQLError(str(exc)) from exc
        if self._query_lane(dashboard_id) == QueryLane.TELEMETRY:
            # The telemetry slots don't cover the events cluster, so resolve an `all` range here and the run reads its
            # earliest event from cache.
            try:
                with self._earliest_event_slot(dashboard_id):
                    _ = self._date_from
            except ValueError as exc:
                raise ExposedHogQLError(str(exc)) from exc
        return super()._call_with_rate_limits(dashboard_id=dashboard_id)

    def _query_lane(self, dashboard_id: int | None) -> QueryLane:
        # Stored metrics read Snuffle and the metrics tables, so the events-cluster slots protect nothing there.
        # A derived metric scans spans or logs on the events cluster, so it keeps the analytics slots.
        if dashboard_id is not None and self._dashboard_v2_enabled and not self._reads_derived_metrics:
            return QueryLane.TELEMETRY
        return QueryLane.ANALYTICS

    def _earliest_event_slot(self, dashboard_id: int | None) -> AbstractContextManager[None]:
        # `all` looks up the earliest event on the events cluster, so it takes the analytics slots.
        if self.query.dateRange and self.query.dateRange.date_from == "all":
            return query_concurrency_slots(self.team, dashboard_id=dashboard_id, query_lane=QueryLane.ANALYTICS)
        return nullcontext()

    def _tail_refresh_enabled(self, dashboard_id: int | None) -> bool:
        # Only the builder's HogQL engine buckets the way the splice assumes. A raw clause ranks and labels
        # its series over the whole window, and a derived metric runs on another engine. A formula returns
        # only its own series, so it hides whether a grouped input clause reached the series cap.
        date_range = self.query.dateRange
        return (
            dashboard_id is not None
            and (self.query.language or MetricsQueryLanguage.BUILDER) == MetricsQueryLanguage.BUILDER
            and (date_range is None or date_range.date_to is None)
            and not self._reads_derived_metrics
            and not (self.query.formula and any(clause.groupBy for clause in self.query.clauses))
            and not any(
                MetricAggregation(clause.aggregation.value if clause.aggregation else "none").is_raw
                for clause in self.query.clauses
            )
            and self._dashboard_v2_enabled
        )

    def _calculate_with_tail(self, tail: TailRefresh[MetricsQueryResponse]) -> MetricsQueryResponse:
        request = self._builder_request()
        interval = _resolve_interval(request.date_from, request.date_to, request.interval)
        clause_order = [clause.name for clause in request.clauses]

        def calculate(date_from: datetime) -> MetricsQueryResponse:
            return self._response(
                run_metric_query(team=self.team, request=replace(request, date_from=date_from, interval=interval))
            )

        def merge(
            cached: MetricsQueryResponse, fresh: MetricsQueryResponse, start: datetime, cut: datetime
        ) -> MetricsQueryResponse | None:
            merged = merge_series(
                cached.results,
                fresh.results,
                start=start,
                cut=cut,
                clause_order=clause_order,
                formula=request.formula is not None,
            )
            return MetricsQueryResponse(results=merged) if merged is not None else None

        return tail.run(
            response_type=MetricsQueryResponse,
            date_from=request.date_from,
            date_to=request.date_to,
            interval=interval,
            calculate=calculate,
            merge=merge,
            compare=lambda spliced, full: compare_series(spliced.results, full.results),
            can_merge=lambda cached: not clause_at_cap(cached.results),
        )

    @cached_property
    def _date_range(self) -> QueryDateRange:
        return metrics_query_date_range(self.team, self.query.dateRange)

    @cached_property
    def _date_from(self) -> datetime:
        # Resolved once per runner: an `all` range looks up the earliest event, and a team with no events isn't cached.
        return self._date_range.date_from()

    @cached_property
    def _reads_derived_metrics(self) -> bool:
        return bool(derived_metric_resources(clause.metricName for clause in self.query.clauses))

    @cached_property
    def _precompute_enabled(self) -> bool:
        return precompute_enabled(self.team)

    @property
    def _viewer_is_member(self) -> bool:
        user = cast("Optional[User | SharedLinkUser]", self.user)
        return user is not None and not user.is_anonymous

    def _run_planned(self) -> list[MetricSeries] | None:
        """A builder tile that a precomputed metric covers reads its stored buckets, ahead of the tail refresh.
        Every other query gets None and runs as before."""
        if (
            self._tile_dashboard_id is None
            or (self.query.language or MetricsQueryLanguage.BUILDER) != MetricsQueryLanguage.BUILDER
            or not self._precompute_enabled
        ):
            return None
        result = run_planned_metric_query(
            team=self.team, request=self._builder_request(), record_use=self._viewer_is_member
        )
        if isinstance(result, MetricQueryProvenanceContract):
            self._provenance = result
            return None
        return self._keep_precompute(result)

    def _keep_precompute(self, result: MetricQueryResult) -> list[MetricSeries]:
        self._provenance, self._shadow = result.provenance, result.shadow
        return result.series

    def _query_executed_event_properties(self) -> dict[str, Any]:
        if self._provenance is None:
            return {}
        return {
            "precompute_provenance": _EVENT_PROVENANCE[self._provenance.mode],
            "precompute_shadow_checked": self._shadow is not None,
            "precompute_shadow_max_rel_diff": self._shadow.max_relative_difference if self._shadow else None,
            "precompute_shadow_mismatched_points": self._shadow.mismatched_points if self._shadow else None,
        }

    @cached_property
    def _dashboard_v2_enabled(self) -> bool:
        # `dashboard-v2` is aggregated by project, so the distinct id doesn't decide it.
        return posthog_feature_flag_enabled(
            DASHBOARD_V2_FEATURE_FLAG,
            str(getattr(self.user, "distinct_id", None) or self.team.uuid),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
            only_evaluate_locally=True,
        )

    def _load_all_options(self, dashboard_id: int | None = None) -> dict[str, Variable]:
        if self._loaded_variables is None:
            self._enforce_alpha_gates_without_a_request_user()
            variables = from_query(self.query.variables)
            definitions = query_definitions(self.query.variables)
            if definitions and self.query.language == MetricsQueryLanguage.SQL:
                slot = partial(
                    query_concurrency_slots,
                    self.team,
                    dashboard_id=dashboard_id,
                    query_lane=self._query_lane(dashboard_id),
                )
                with self._earliest_event_slot(dashboard_id):
                    date_from, date_to = self._date_from, self._date_range.date_to()
                variables = fill_all_values(
                    team=self.team,
                    names=sql_referenced_names(self.query.sql),
                    variables=variables,
                    definitions=definitions,
                    date_from=date_from,
                    date_to=date_to,
                    slot=slot,
                )
            self._loaded_variables = variables
        return self._loaded_variables

    def _calculate(self) -> MetricsQueryResponse:
        self._enforce_alpha_gates_without_a_request_user()
        try:
            series = self._run_planned()
            if series is None and self._tail is not None:
                response = self._calculate_with_tail(self._tail)
            else:
                response = self._response(self._run() if series is None else series)
        except ValueError as exc:
            # The facade signals user errors (bad formula, unknown clause alias, bad
            # quantile) with ValueError; /query only exposes typed errors, so a bare
            # ValueError would surface as a 500 instead of a 400.
            raise ExposedHogQLError(str(exc)) from exc
        response.provenance = self._provenance_response()
        return response

    @staticmethod
    def _response(series: list[MetricSeries]) -> MetricsQueryResponse:
        return MetricsQueryResponse(
            results=[
                MetricsQuerySeries(
                    labels=s.labels,
                    points=[MetricsQueryPoint(time=p.time, value=p.value) for p in s.points],
                    metricName=s.metric_name,
                    clause=s.clause,
                    unit=s.unit or None,
                    histogramBounds=list(s.histogram_bounds) if s.histogram_bounds is not None else None,
                )
                for s in series
            ]
        )

    def _provenance_response(self) -> MetricsQueryProvenance | None:
        if self._provenance is None:
            return None
        until = self._provenance.precomputed_until
        return MetricsQueryProvenance(
            mode=self._provenance.mode.value,
            precomputedUntil=until.isoformat() if until is not None else None,
            reasons=list(self._provenance.reasons) or None,
        )

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter) -> None:
        # Metric label predicates are not PostHog property filters, so the dashboard's
        # property filters do not apply. Its date range and variables do, in all three languages.
        if dashboard_filter.date_from or dashboard_filter.date_to:
            self.query.dateRange = DateRange(
                date_from=dashboard_filter.date_from,
                date_to=dashboard_filter.date_to,
            )
        if dashboard_filter.metricVariables:
            self._apply_variables(dashboard_filter)

    def _apply_variables(self, dashboard_filter: DashboardFilter) -> None:
        # The values go into the query, so each selection has its own cache entry and reaches the async worker.
        # No options query runs here: this step comes before the access checks and the cache lookup.
        sql_names = sql_referenced_names(self.query.sql)
        variables = from_dashboard(dashboard_filter.metricVariables)
        definitions: dict[str, MetricsDashboardVariable] = {}
        if (self.query.language or MetricsQueryLanguage.BUILDER) == MetricsQueryLanguage.SQL:
            definitions = all_definitions(
                sql_names,
                variables,
                {definition.name: definition for definition in dashboard_filter.metricVariables or []},
            )
        names = dict.fromkeys(
            [
                *referenced_names(self.query.interval),
                *referenced_names(self.query.promql),
                *sql_names,
                *(name for clause in self.query.clauses for name in filter_referenced_names(clause.filters)),
                *(name for definition in definitions.values() for name in referenced_names(definition.query)),
            ]
        )
        self.query.variables = to_query(variables, names, definitions) or None

    def _sends_promql(self) -> bool:
        """Whether the query runs PromQL on Snuffle: as its language, or to load the options of a variable set to All."""
        if self.query.language == MetricsQueryLanguage.PROMQL:
            return True
        return any(
            definition.source == MetricsDashboardVariableSource.PROMQL
            for definition in query_definitions(self.query.variables).values()
        )
