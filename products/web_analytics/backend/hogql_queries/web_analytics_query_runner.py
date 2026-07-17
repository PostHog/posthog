import typing
from abc import ABC
from datetime import datetime, timedelta
from math import ceil
from time import perf_counter
from typing import Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings

import structlog
from prometheus_client import Counter
from structlog.contextvars import bound_contextvars

from posthog.schema import (
    ActionConversionGoal,
    CohortPropertyFilter,
    CustomEventConversionGoal,
    EventPropertyFilter,
    PersonPropertyFilter,
    SessionPropertyFilter,
    WebExternalClicksTableQuery,
    WebGoalsQuery,
    WebNotableChangesQuery,
    WebOverviewQuery,
    WebPageURLSearchQuery,
    WebStatsTableQuery,
    WebVitalsPathBreakdownQuery,
)

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, apply_path_cleaning, property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tag_value, tag_queries
from posthog.hogql_queries.query_runner import AnalyticsQueryResponseProtocol, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import User
from posthog.models.filters.mixins.utils import cached_property
from posthog.rbac.user_access_control import UserAccessControl

from products.actions.backend.models.action import Action
from products.web_analytics.backend.hogql_queries.metrics import (
    WEB_ANALYTICS_QUERY_COUNTER,
    WEB_ANALYTICS_QUERY_DURATION,
    WEB_ANALYTICS_QUERY_ERRORS,
)
from products.web_analytics.backend.hogql_queries.traffic_type import get_traffic_category_expr, get_traffic_type_expr
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import compute_filters_eligibility_hash

logger = structlog.get_logger(__name__)

# Tracks how often a web analytics query is served without the events↔sessions join,
# so the trial rollout can be monitored per query family against the join path.
WEB_ANALYTICS_NO_JOIN_SERVED = Counter(
    "web_analytics_no_join_served_total",
    "Web analytics queries served by a no-session-join fast path.",
    ["family"],
)

# Ceiling on the number of matching session ids a session-id-set fast path may ship
# to shards via GLOBAL IN. Cross-team prod validation: memory scales ~linearly at
# ~190 MiB per million ids on the sessions side; the id-set shape beats the join at
# 4-5M ids (3.8s/727MiB vs 6.8s/4.5GiB at 3.8M); the extrapolated crossover where
# the shipped set stops paying is ~20M. 10M caps session-id-set memory at ~2 GiB —
# under half the join's typical footprint — with margin before the crossover.
SESSION_ID_SET_MAX_MATCHING_SESSIONS = 10_000_000

WebQueryNode = Union[
    WebOverviewQuery,
    WebStatsTableQuery,
    WebGoalsQuery,
    WebExternalClicksTableQuery,
    WebVitalsPathBreakdownQuery,
    WebPageURLSearchQuery,
    WebNotableChangesQuery,
]

WAR = typing.TypeVar("WAR", bound=AnalyticsQueryResponseProtocol)


class WebAnalyticsQueryRunner(AnalyticsQueryRunner[WAR], ABC):
    # The `sampling`/`samplingFactor` query fields are accepted for API schema
    # compatibility but intentionally ignored: web analytics always returns
    # exact numbers. Sampling was never exposed in the product UI and prod
    # query_log shows zero queries requesting it, so runners neither inject
    # SAMPLE clauses nor scale results.
    query: WebQueryNode
    query_type: type[WebQueryNode]

    def query_strategy(self) -> str | None:
        return None

    def clickhouse_query_type(self) -> str | None:
        return None

    def validate_query_runner_access(self, user: User) -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        return user_access_control.assert_access_level_for_resource("web_analytics", "viewer")

    def calculate(self) -> WAR:
        # `filters_eligibility_hash` is bound on structlog contextvars here so every
        # structured log emitted inside this request — `web_analytics_query`,
        # each lazy-precompute path's `*_rejected` / `*_eligible`, and the
        # framework's `lazy_computation.executed` — automatically carries it
        # via the `merge_contextvars` processor. Joining log streams by cache
        # key needs no further plumbing. The body is inlined inside the
        # contextvar block (rather than delegated to a helper) so existing
        # tests that call `WebAnalyticsQueryRunner.calculate(<MagicMock>)`
        # exercise it directly.
        with bound_contextvars(filters_eligibility_hash=self.filters_eligibility_hash):
            # Tag everything ClickHouse will see for this request in one call so
            # every downstream `sync_execute` (live, preagg, lazy precompute)
            # inherits a coherent `log_comment` payload.
            #
            # `product`/`feature` are required so DEBUG-mode `sync_execute` doesn't
            # trip `UntaggedQueryError`. `query` is set here because the HTTP
            # layer (`posthog/api/services/query.py`) tags only the wrapping
            # payload — the weekly digest workflow (and any other non-HTTP
            # caller) reaches the runner directly with `log_comment.query`
            # empty, so each runner records its own payload.
            #
            # `filters_eligibility_hash` deliberately stays out of the tag
            # payload: `system.query_log` retention is sub-day on prod ClickHouse,
            # so the hash is only useful on a multi-day source. It lives on the
            # structlog contextvar (Loki, ~14 d retention) only.
            query_kind = getattr(self.query, "kind", "Unknown")
            breakdown_value = getattr(self.query, "breakdownBy", None)
            breakdown_label = breakdown_value.value if breakdown_value is not None else "none"
            has_conversion_goal = "true" if getattr(self.query, "conversionGoal", None) else "false"

            tag_kwargs: dict[str, object] = {
                "product": Product.WEB_ANALYTICS,
                "feature": Feature.QUERY,
                "query": self.query.model_dump(mode="json"),
            }
            if breakdown_value is not None:
                tag_kwargs["breakdown_by"] = [breakdown_value.value]
            tag_queries(**tag_kwargs)

            logger.info(
                "web_analytics_query_started",
                team_id=self.team.pk,
                query_kind=query_kind,
            )

            start = perf_counter()
            response: Optional[WAR] = None
            error_type = ""
            query_strategy: str | None = None
            clickhouse_query_type: str | None = None

            try:
                response = super().calculate()
                return response
            except Exception as exc:
                error_type = type(exc).__name__
                raise
            finally:
                duration_s = perf_counter() - start

                try:
                    query_strategy = self.query_strategy()
                    clickhouse_query_type = self.clickhouse_query_type()
                except Exception:
                    query_strategy = query_strategy or "strategy_resolution_failed"
                    clickhouse_query_type = clickhouse_query_type or None

                pre_compute_strategy_label = "unknown"
                if response is not None:
                    strategy = getattr(response, "preComputeStrategy", None)
                    if strategy is not None:
                        pre_compute_strategy_label = str(strategy)

                query_strategy_label = query_strategy or "none"
                metric_labels = {
                    "query_kind": query_kind,
                    "query_strategy": query_strategy_label,
                    "pre_compute_strategy": pre_compute_strategy_label,
                    "breakdown": breakdown_label,
                    "has_conversion_goal": has_conversion_goal,
                }
                WEB_ANALYTICS_QUERY_DURATION.labels(**metric_labels).observe(duration_s)
                WEB_ANALYTICS_QUERY_COUNTER.labels(**metric_labels).inc()

                if error_type:
                    WEB_ANALYTICS_QUERY_ERRORS.labels(
                        query_kind=query_kind,
                        query_strategy=query_strategy_label,
                        breakdown=breakdown_label,
                        error_type=error_type,
                    ).inc()

                logger.info(
                    "web_analytics_query",
                    team_id=self.team.pk,
                    organization_id=str(self.team.organization_id),
                    user_id=get_query_tag_value("user_id"),
                    query_kind=query_kind,
                    query_strategy=query_strategy,
                    clickhouse_query_type=clickhouse_query_type,
                    breakdown=breakdown_label,
                    has_conversion_goal=has_conversion_goal,
                    pre_compute_strategy=pre_compute_strategy_label,
                    duration_s=round(duration_s, 4),
                    error=bool(error_type),
                    error_type=error_type or None,
                    filter_count=len(self.query.properties),
                    date_from=self.query_date_range.date_from_str,
                    date_to=self.query_date_range.date_to_str,
                )

    @cached_property
    def should_skip_session_join(self) -> bool:
        """Whether this query can be served by independent events/sessions scans.

        The events↔sessions join exists so filters on events can constrain which
        sessions contribute to session-level metrics (duration, bounce rate). When
        nothing in the query constrains session membership, both sides can be
        aggregated independently — the join only multiplies cost, because the
        sessions-side subquery is re-executed on every shard of the events cluster
        (10× read amplification on US prod; measured 5.5-14.7× latency and 8-25×
        memory vs the two-scan variants).

        Runners that support a no-join query shape check this gate; anything not
        covered falls through to the join path untouched.
        """
        if not self._team_in_no_join_rollout():
            return False
        if getattr(self.query, "conversionGoal", None):
            return False
        if getattr(self.query, "properties", None):
            return False
        # Test-account filters are event/person property filters, so they constrain
        # session membership the same way user filters do.
        if self._test_account_filters:
            return False
        return True

    def _team_in_no_join_rollout(self) -> bool:
        if self.team.pk in settings.WEB_ANALYTICS_NO_JOIN_TEAM_IDS:
            return True
        percent = settings.WEB_ANALYTICS_NO_JOIN_ROLLOUT_PERCENT
        # Deterministic per-team bucketing: query results must come from one code
        # path for everyone on a team, so the rollout unit is the team, not the user.
        return percent > 0 and self.team.pk % 100 < percent

    def _session_id_set_common_eligibility(self) -> bool:
        """Shared gates for the session-id-set fast paths (filtered two-scan shape).

        A filter is only evaluable events-side when it's an event property filter
        (user filters) or an event/person test-account filter (person props via
        person-on-events). Session/cohort filters can't feed the id collection
        and keep the join path. Runners add their own shape-specific gates on top.
        """
        if self.team.pk not in settings.WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS:
            return False
        if getattr(self.query, "conversionGoal", None):
            return False
        properties = getattr(self.query, "properties", None) or []
        if not properties and not self._test_account_filters:
            return False
        if not all(isinstance(p, EventPropertyFilter) for p in properties):
            return False
        if not all(f.get("type") in ("event", "person") for f in self._test_account_filters):
            return False
        return True

    def _run_session_id_set_preflight(self, filters: ast.Expr, query_type: str) -> bool:
        """Preflight: is the filtered session-id set small enough to ship to shards?

        A cheap count over the filtered events (materialized columns only) — the
        events scan is work the id collection does anyway, so this bounds the
        worst case at one extra sub-second query for eligible teams. Fails closed
        to the join path on error.
        """
        count_query = parse_select(
            """
SELECT uniq(events.$session_id_uuid) AS matching_sessions
FROM events
WHERE and(
    events.$session_id_uuid IS NOT NULL,
    {event_type_expr},
    {inside_timestamp_period},
    {filters},
)
            """,
            placeholders={
                "event_type_expr": self.event_type_expr,
                "inside_timestamp_period": self._periods_expression("timestamp"),
                "filters": filters,
            },
        )
        try:
            response = execute_hogql_query(
                query_type=query_type,
                query=count_query,
                team=self.team,
                user=self.user,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            matching = response.results[0][0] if response.results else None
            if matching is None:
                return False
            return matching <= SESSION_ID_SET_MAX_MATCHING_SESSIONS
        except Exception as e:
            logger.exception("web_analytics_session_id_set_preflight_failed", error=e, query_type=query_type)
            return False

    @cached_property
    def filters_eligibility_hash(self) -> Optional[str]:
        """Stable hash of the user-facing query inputs that would fragment a
        precompute cache key. Bound on the structlog contextvars in
        `calculate()` so every log emitted inside the request — including the
        framework's `lazy_computation.executed` — carries it automatically and
        the log streams can be joined for queries-per-distinct-cache-key
        analysis. See `compute_filters_eligibility_hash` for the exact field set."""
        try:
            return compute_filters_eligibility_hash(self.query, self.team.timezone)
        except Exception:
            return None

    @cached_property
    def _timezone_info(self) -> ZoneInfo:
        # Respect the convertToProjectTimezone modifier for date range calculation
        # When convertToProjectTimezone=False, use UTC for both date boundaries AND column conversion
        if self.modifiers and not self.modifiers.convertToProjectTimezone:
            return ZoneInfo("UTC")
        return self.team.timezone_info

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            timezone_info=self._timezone_info,
            interval=self.query.interval,
            now=datetime.now(self._timezone_info),
        )

    @cached_property
    def query_compare_to_date_range(self):
        if self.query.compareFilter is not None:
            if isinstance(self.query.compareFilter.compare_to, str):
                return QueryCompareToDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=self.query.interval,
                    now=datetime.now(self._timezone_info),
                    timezone_info=self._timezone_info,
                    compare_to=self.query.compareFilter.compare_to,
                )
            elif self.query.compareFilter.compare:
                return QueryPreviousPeriodDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=self.query.interval,
                    now=datetime.now(self._timezone_info),
                    timezone_info=self._timezone_info,
                )

        return None

    def _current_period_expression(self, field="start_timestamp"):
        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_date_range.date_from_as_hogql(),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_date_range.date_to_as_hogql(),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )

    def _previous_period_expression(self, field="start_timestamp"):
        # NOTE: Returning `ast.Constant(value=None)` is painfully slow, make sure we return a boolean
        if not self.query_compare_to_date_range:
            return ast.Constant(value=False)

        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_compare_to_date_range.date_from_as_hogql(),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_compare_to_date_range.date_to_as_hogql(),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )

    def _periods_expression(self, field="timestamp"):
        return ast.Call(
            name="or",
            args=[
                self._current_period_expression(field),
                self._previous_period_expression(field),
            ],
        )

    @cached_property
    def pathname_property_filter(self) -> Optional[EventPropertyFilter]:
        for p in self.query.properties:
            if isinstance(p, EventPropertyFilter) and p.key == "$pathname":
                return p
        return None

    @cached_property
    def property_filters_without_pathname(
        self,
    ) -> list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter, CohortPropertyFilter]]:
        return [p for p in self.query.properties if p.key != "$pathname"]

    @cached_property
    def conversion_goal_expr(self) -> Optional[ast.Expr]:
        if isinstance(self.query.conversionGoal, ActionConversionGoal):
            try:
                action = Action.objects.get(
                    pk=self.query.conversionGoal.actionId, team__project_id=self.team.project_id
                )
            except Action.DoesNotExist:
                raise QueryError(
                    f"Conversion goal action with id={self.query.conversionGoal.actionId} not found in this project."
                )
            return action_to_expr(action)
        elif isinstance(self.query.conversionGoal, CustomEventConversionGoal):
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.conversionGoal.customEventName),
            )
        else:
            return None

    @cached_property
    def conversion_count_expr(self) -> Optional[ast.Expr]:
        if self.conversion_goal_expr:
            return ast.Call(name="countIf", args=[self.conversion_goal_expr])
        else:
            return None

    @cached_property
    def conversion_person_id_expr(self) -> Optional[ast.Expr]:
        if self.conversion_goal_expr:
            return ast.Call(
                name="any",
                args=[
                    ast.Call(
                        name="if",
                        args=[
                            self.conversion_goal_expr,
                            ast.Field(chain=["events", "person_id"]),
                            ast.Constant(value=None),
                        ],
                    )
                ],
            )
        else:
            return None

    @cached_property
    def event_type_expr(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value="$pageview")
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value="$screen")
            ),
        ]

        if self.conversion_goal_expr:
            exprs.append(self.conversion_goal_expr)

        return ast.Or(exprs=exprs)

    def period_aggregate(
        self,
        function_name: str,
        column_name: str,
        start: ast.Expr,
        end: ast.Expr,
        alias: Optional[str] = None,
        params: Optional[list[ast.Expr]] = None,
    ):
        expr = ast.Call(
            name=function_name + "If",
            params=params,
            args=[
                ast.Field(chain=[column_name]),
                ast.Call(
                    name="and",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.Field(chain=["start_timestamp"]),
                            right=start,
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=ast.Field(chain=["start_timestamp"]),
                            right=end,
                        ),
                    ],
                ),
            ],
        )

        if alias is not None:
            return ast.Alias(alias=alias, expr=expr)

        return expr

    def session_where(self, include_previous_period: Optional[bool] = None):
        properties = [
            parse_expr(
                "events.timestamp <= {date_to} AND events.timestamp >= minus({date_from}, toIntervalHour(1))",
                placeholders={
                    "date_from": (
                        self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql()
                    ),
                    "date_to": self.query_date_range.date_to_as_hogql(),
                },
            ),
            *self.property_filters_without_pathname,
            *self._test_account_filters,
        ]
        return property_to_expr(
            properties,
            self.team,
        )

    def session_having(self, include_previous_period: Optional[bool] = None):
        properties: list[Union[ast.Expr, EventPropertyFilter]] = [
            parse_expr(
                "min_timestamp >= {date_from}",
                placeholders={
                    "date_from": (
                        self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql()
                    ),
                },
            )
        ]
        pathname = self.pathname_property_filter
        if pathname:
            properties.append(
                EventPropertyFilter(
                    key="session_initial_pathname",
                    label=pathname.label,
                    operator=pathname.operator,
                    value=pathname.value,
                )
            )
        return property_to_expr(
            properties,
            self.team,
        )

    def sessions_table_properties(self, include_previous_period: Optional[bool] = None):
        properties = [
            parse_expr(
                "sessions.min_timestamp >= {date_from}",
                placeholders={
                    "date_from": (
                        self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql()
                    ),
                },
            )
        ]
        return property_to_expr(
            properties,
            self.team,
        )

    def events_where(self):
        properties = [self.events_where_data_range(), self.query.properties, self._test_account_filters]

        return property_to_expr(
            properties,
            self.team,
        )

    def events_where_data_range(self):
        return property_to_expr(
            [
                parse_expr(
                    "events.timestamp >= {date_from}",
                    placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
                ),
                parse_expr(
                    "events.timestamp <= {date_to}",
                    placeholders={"date_to": self.query_date_range.date_to_as_hogql()},
                ),
            ],
            self.team,
        )

    @cached_property
    def _test_account_filters(self):
        if not self.query.filterTestAccounts:
            return []
        if isinstance(self.team.test_account_filters, list) and len(self.team.test_account_filters) > 0:
            return self.team.test_account_filters
        else:
            return []

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
        if not self.query.doPathCleaning:
            return path_expr

        return apply_path_cleaning(path_expr, self.team)

    def _get_traffic_type_expr(
        self, user_agent_expr: ast.Expr | None = None, ip_expr: ast.Expr | None = None
    ) -> ast.Expr:
        return get_traffic_type_expr(
            user_agent_expr or ast.Field(chain=["events", "properties", "$raw_user_agent"]),
            ip_expr or ast.Field(chain=["events", "properties", "$ip"]),
        )

    def _get_traffic_category_expr(
        self, user_agent_expr: ast.Expr | None = None, ip_expr: ast.Expr | None = None
    ) -> ast.Expr:
        return get_traffic_category_expr(
            user_agent_expr or ast.Field(chain=["events", "properties", "$raw_user_agent"]),
            ip_expr or ast.Field(chain=["events", "properties", "$ip"]),
        )

    def get_cache_key(self) -> str:
        original = super().get_cache_key()
        return f"{original}_{self.team.path_cleaning_filters}"

    @cached_property
    def events_session_property(self):
        # we should delete this once SessionsV2JoinMode is always uuid, eventually we will always use $session_id_uuid
        if self.query.modifiers and self.query.modifiers.sessionsV2JoinMode == "uuid":
            return parse_expr("events.$session_id_uuid")
        else:
            return parse_expr("events.$session_id")

    @cached_property
    def events_session_id_present(self) -> ast.Expr:
        """True when the event carries a usable session id.

        Uses the nullable-UUID materialized column in both join modes: a missing
        `$session_id` materializes as an empty string (not NULL) and a malformed
        one isn't a UUID — both become NULL here and are excluded, which is
        exactly what the join path does implicitly (their NULL session start
        fails the period HAVING). The no-join query shapes need the explicit
        guard to match.
        """
        return parse_expr("events.$session_id_uuid IS NOT NULL")


def map_columns(results, mapper: dict[int, typing.Callable]):
    return [[mapper[i](data, row) if i in mapper else data for i, data in enumerate(row)] for row in results]
