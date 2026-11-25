"""Serve web overview and stats table queries from the dimensional precompute tables.

The dimensional tables have the same columns as the legacy pre-aggregated tables, so the
legacy query builders run unchanged against them. Two differences need the subclasses here:
the table names, and a `job_id IN (...)` filter. A recent window can hold several job
generations at once, and without the filter `sumMerge`/`uniqMerge` would count each
generation.
"""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING, Union
from uuid import UUID

from django.utils import timezone

import structlog
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.errors import QueryErrorCategory, classify_query_error
from posthog.models.team.event_retention import events_retention_months_for_team
from posthog.ph_client import feature_enabled_or_false

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import (
    WebAnalyticsPreAggregatedQueryBuilder,
)
from products.web_analytics.backend.hogql_queries.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    DIMENSIONAL_SEMANTIC_MODIFIER_FIELDS,
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    DimensionalJobIds,
    dimensional_insert_modifiers,
    dimensional_job_ids,
    sessions_coverage_floor,
)
from products.web_analytics.backend.hogql_queries.web_overview_pre_aggregated import (
    WebOverviewPreAggregatedQueryBuilder,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
    from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
    from products.web_analytics.backend.hogql_queries.web_page_directory import WebPageDirectoryQueryRunner

    DimensionalReadRunner = Union[WebStatsTableQueryRunner, WebOverviewQueryRunner, WebPageDirectoryQueryRunner]

logger = structlog.get_logger(__name__)

# The same flag gates the frontend toggle, so a request that sets the modifier without the flag is ignored.
WEB_ANALYTICS_QUERY_MODIFIERS_FLAG = "web-analytics-query-modifiers"

# The tables have no column for these keys, or store a session-level value that differs from what the
# live filter matches. Gclid, fbclid and gad_source are stored as booleans, so a value filter cannot match them.
_INEXACT_PROPERTY_KEYS = frozenset(
    {
        "$browser_version",
        "$os_version",
        "$geoip_country_name",
        "$geoip_time_zone",
        "$entry_gclid",
        "$entry_fbclid",
        "$entry_gad_source",
    }
)


def ready_dimensional_job_ids(
    runner: "DimensionalReadRunner",
    tables: Collection[str],
) -> DimensionalJobIds | None:
    """The job ids to read when the query opted in and `tables` cover its whole range,
    including the compare period. None means the caller uses its next path."""
    web_query_modifiers = runner.query.webQueryModifiers
    if not (web_query_modifiers and web_query_modifiers.useDimensionalTables):
        return None
    if not _query_modifiers_flag_enabled(runner):
        return None
    if _has_inexact_property_filter(runner):
        return None
    # The tables are built without a user, so they cannot honor per-user property restrictions.
    if team_has_property_access_rules(team_id=runner.team.pk):
        return None
    # The writer builds all traffic, so the rows cannot exclude the team's test accounts.
    if runner._test_account_filters:
        return None

    # A per-request override, such as a longer bounce duration or different custom channel rules, would
    # count the stored rows differently.
    build_modifiers = dimensional_insert_modifiers(runner.team)
    if any(
        getattr(runner.modifiers, field) != getattr(build_modifiers, field)
        for field in DIMENSIONAL_SEMANTIC_MODIFIER_FIELDS
    ):
        return None

    periods = [runner.query_date_range]
    if runner.query_compare_to_date_range:
        periods.append(runner.query_compare_to_date_range)
    if not all(_fits_whole_hour_buckets(period.date_from(), period.date_to()) for period in periods):
        return None

    start = min(period.date_from() for period in periods)
    if _crosses_events_retention_floor(runner, start):
        return None
    sessions_floor = sessions_coverage_floor(build_modifiers)
    if sessions_floor is not None and start < sessions_floor:
        return None

    # A range can end after now, for example at the end of the current day in the project
    # timezone. No rows exist past now, and the writer does not build the next UTC day yet.
    end = min(runner.query_date_range.date_to(), timezone.now())
    try:
        return dimensional_job_ids(
            runner.team, start.astimezone(UTC), end.astimezone(UTC), tables=tables, modifiers=build_modifiers
        )
    except Exception:
        logger.exception("web_dimensional_job_ids_lookup_failed", team_id=runner.team.pk)
        return None


class DimensionalReadFailure(Enum):
    # Cancelled by the user or the server, or refused for cluster capacity: no other read may run.
    RERAISE = auto()
    # Too slow or too large: the cheaper lazy and v2 reads may run, but not the live query, which
    # reads more data than the dimensional query that failed.
    SKIP_LIVE = auto()
    FALL_BACK = auto()


def classify_dimensional_read_failure(error: Exception) -> DimensionalReadFailure:
    category = classify_query_error(error)
    if category in (QueryErrorCategory.CANCELLED, QueryErrorCategory.RATE_LIMITED):
        return DimensionalReadFailure.RERAISE
    if category == QueryErrorCategory.QUERY_PERFORMANCE_ERROR:
        return DimensionalReadFailure.SKIP_LIVE
    return DimensionalReadFailure.FALL_BACK


def dimensional_precompute_stale(job_ids: DimensionalJobIds | None) -> bool | None:
    return True if job_ids and job_ids.stale else None


def dimensional_precomputed_at(job_ids: DimensionalJobIds | None) -> str | None:
    if job_ids is None or job_ids.computed_at is None:
        return None
    return job_ids.computed_at.astimezone(UTC).isoformat()


def _query_modifiers_flag_enabled(runner: "DimensionalReadRunner") -> bool:
    team = runner.team
    user = runner.user
    return feature_enabled_or_false(
        WEB_ANALYTICS_QUERY_MODIFIERS_FLAG,
        str(user.distinct_id) if user and user.distinct_id else str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        person_properties={"email": user.email} if user else None,
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def _has_inexact_property_filter(runner: "DimensionalReadRunner") -> bool:
    for prop in runner.query.properties:
        key = getattr(prop, "key", None)
        if key in _INEXACT_PROPERTY_KEYS:
            return True
        # The tables hold the session's initial referring domain, not the referrer of each event.
        if key == "$referring_domain" and getattr(prop, "type", None) == "event":
            return True
    return False


def _fits_whole_hour_buckets(date_from: datetime, date_to: datetime) -> bool:
    """Whether `period_bucket >= date_from AND period_bucket <= date_to` selects exactly the
    events in the range. Each bucket holds one UTC hour, so the start must be an hour boundary
    and the inclusive end must be the last microsecond of an hour. An end after now is also
    exact, because the bucket of the current hour holds only events up to now."""
    if not _is_utc_hour_boundary(date_from):
        return False
    return _is_utc_hour_boundary(date_to + timedelta(microseconds=1)) or date_to >= timezone.now()


def _is_utc_hour_boundary(moment: datetime) -> bool:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0) == moment


def _crosses_events_retention_floor(runner: "DimensionalReadRunner", start: datetime) -> bool:
    # READY jobs outlive the retention window. The live path floors events at
    # `timestamp > now() - retention`, so a range that starts at or before that floor
    # would show older traffic here than live does.
    retention_months = events_retention_months_for_team(runner.team, runner.team.pk)
    if retention_months is None:
        return False
    return start <= timezone.now() - relativedelta(months=retention_months)


class DimensionalTablesMixin(WebAnalyticsPreAggregatedQueryBuilder):
    job_ids: DimensionalJobIds

    @property
    def stats_table(self) -> str:
        return WEB_STATS_DIMENSIONAL_READ_TABLE

    @property
    def bounces_table(self) -> str:
        return WEB_BOUNCES_DIMENSIONAL_READ_TABLE

    def _get_channel_type_expr(self) -> ast.Expr:
        # The writer stores the session's channel type with the team's custom rules applied, and the rules
        # are part of the job identity, so the column always matches the rules of the jobs being read.
        return ast.Field(chain=["channel_type"])

    def _job_ids_for(self, table_name: str) -> list[UUID] | None:
        return self.job_ids.stats if table_name == WEB_STATS_DIMENSIONAL_READ_TABLE else self.job_ids.bounces

    def _get_filters(self, table_name: str, exclude_pathname: bool = False) -> ast.And:
        filters = super()._get_filters(table_name, exclude_pathname=exclude_pathname)
        job_ids = self._job_ids_for(table_name)
        if job_ids is None:
            raise ValueError(f"No dimensional job ids were looked up for {table_name}")
        job_id_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=[table_name, "job_id"]),
            right=ast.Constant(value=[str(job_id) for job_id in job_ids]),
        )
        return ast.And(exprs=[*filters.exprs, job_id_filter])


class DimensionalStatsTableQueryBuilder(DimensionalTablesMixin, StatsTablePreAggregatedQueryBuilder):
    def __init__(self, runner: "WebStatsTableQueryRunner", job_ids: DimensionalJobIds) -> None:
        super().__init__(runner)
        self.job_ids = job_ids


class DimensionalWebOverviewQueryBuilder(DimensionalTablesMixin, WebOverviewPreAggregatedQueryBuilder):
    """Reads visitors, views and sessions from the stats table and bounce rate and duration from the bounces table.

    The stats table has one row per session and host (and other per-event dimensions), so a host filter keeps the
    matching events' rows, as the live query does. The bounces table has one row per session, so a host filter
    matches a session through the session's `session_hosts` list instead of its single `host`."""

    def __init__(self, runner: "WebOverviewQueryRunner", job_ids: DimensionalJobIds) -> None:
        super().__init__(runner)
        self.job_ids = job_ids

    def get_query(self) -> ast.SelectQuery:
        if self.runner.query.conversionGoal:
            return super().get_query()

        periods = self.get_date_ranges()
        counts = parse_select(
            """
            SELECT
                {persons_current} AS unique_persons,
                {persons_previous} AS previous_unique_persons,
                {pageviews_current} AS pageviews,
                {pageviews_previous} AS previous_pageviews,
                {sessions_current} AS unique_sessions,
                {sessions_previous} AS previous_unique_sessions
            FROM {table}
            """,
            placeholders={
                "table": ast.Field(chain=[self.stats_table]),
                "persons_current": self._uniq_merge_if("persons_uniq_state", periods.current_period),
                "persons_previous": self._uniq_merge_if("persons_uniq_state", periods.previous_period),
                "pageviews_current": self._sum_merge_if("pageviews_count_state", periods.current_period),
                "pageviews_previous": self._sum_merge_if("pageviews_count_state", periods.previous_period),
                "sessions_current": self._uniq_merge_if("sessions_uniq_state", periods.current_period),
                "sessions_previous": self._uniq_merge_if("sessions_uniq_state", periods.previous_period),
            },
        )
        assert isinstance(counts, ast.SelectQuery)
        counts.where = self._get_filters(table_name=self.stats_table)

        sessions = parse_select(
            """
            SELECT
                {duration_current} AS avg_session_duration,
                {duration_previous} AS previous_avg_session_duration,
                {bounce_current} AS bounce_rate,
                {bounce_previous} AS previous_bounce_rate
            FROM {table}
            """,
            placeholders={
                "table": ast.Field(chain=[self.bounces_table]),
                "duration_current": self._average_duration(periods.current_period),
                "duration_previous": self._average_duration(periods.previous_period),
                "bounce_current": self._bounce_rate(periods.current_period),
                "bounce_previous": self._bounce_rate(periods.previous_period),
            },
        )
        assert isinstance(sessions, ast.SelectQuery)
        sessions.where = self._get_filters(table_name=self.bounces_table)

        query = parse_select(
            """
            SELECT
                counts.unique_persons AS unique_persons,
                counts.previous_unique_persons AS previous_unique_persons,
                counts.pageviews AS pageviews,
                counts.previous_pageviews AS previous_pageviews,
                counts.unique_sessions AS unique_sessions,
                counts.previous_unique_sessions AS previous_unique_sessions,
                sessions.avg_session_duration AS avg_session_duration,
                sessions.previous_avg_session_duration AS previous_avg_session_duration,
                sessions.bounce_rate AS bounce_rate,
                sessions.previous_bounce_rate AS previous_bounce_rate,
                NULL AS revenue,
                NULL AS previous_revenue
            FROM {counts} AS counts
            CROSS JOIN {sessions} AS sessions
            """,
            placeholders={"counts": counts, "sessions": sessions},
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _bounce_rate(self, period_filter: ast.Expr) -> ast.Expr:
        # Only sessions with a bounce value count, as live's avgIf over `$is_bounce` skips NULL. A session
        # without a pageview (an app session with only $screen events) has none under the default bounce mode.
        return self._average_or_null("bounces_count_state", "bounce_eligible_sessions_state", period_filter)

    def _average_duration(self, period_filter: ast.Expr) -> ast.Expr:
        return self._average_or_null("total_session_duration_state", "total_session_count_state", period_filter)

    def _average_or_null(self, sum_state: str, count_state: str, period_filter: ast.Expr) -> ast.Expr:
        # NULL when no session counts, as live's avgIf returns, so the tile shows no value instead of 0.
        count = self._sum_merge_if(count_state, period_filter)
        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=count, right=ast.Constant(value=0)),
                ast.Call(name="divide", args=[self._sum_merge_if(sum_state, period_filter), count]),
                ast.Constant(value=None),
            ],
        )

    def _get_filters(self, table_name: str, exclude_pathname: bool = False) -> ast.And:
        filters = super()._get_filters(table_name, exclude_pathname=exclude_pathname)
        if table_name != self.bounces_table:
            return filters
        rewritten = _HostSetFilterRewriter(table_name).visit(filters)
        assert isinstance(rewritten, ast.And)
        return rewritten


_HOST_LAMBDA_ARG = "host_in_set"


class _FieldChainCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.chains: list[list[str | int]] = []

    def visit_field(self, node: ast.Field) -> None:
        self.chains.append(node.chain)


class _HostFieldReplacer(CloningVisitor):
    def __init__(self, host_chain: list[str | int]) -> None:
        super().__init__()
        self.host_chain = host_chain

    def visit_field(self, node: ast.Field) -> ast.Field:
        if node.chain == self.host_chain:
            return ast.Field(chain=[_HOST_LAMBDA_ARG])
        return super().visit_field(node)


class _HostSetFilterRewriter(CloningVisitor):
    """Rewrites `$host` filters on the bounces table to match any host in the session's `session_hosts` list.

    Live filters events and keeps a session with at least one matching event, so every operator becomes "some host
    matches": `is not X` keeps a session that also viewed another host, which `NOT has(session_hosts, X)` would drop.
    The host filters of one AND go into a single `arrayExists`, because live applies all of them to the same event."""

    def __init__(self, table_name: str) -> None:
        super().__init__()
        self.host_chain: list[str | int] = [table_name, "host"]
        self.session_hosts_chain: list[str | int] = [table_name, "session_hosts"]

    def _field_chains(self, node: ast.Expr) -> list[list[str | int]]:
        collector = _FieldChainCollector()
        collector.visit(node)
        return collector.chains

    def _references_host(self, node: ast.Expr) -> bool:
        return self.host_chain in self._field_chains(node)

    def _host_only(self, node: ast.Expr) -> bool:
        chains = self._field_chains(node)
        return bool(chains) and all(chain == self.host_chain for chain in chains)

    def _match_any_host(self, node: ast.Expr) -> ast.Expr:
        predicate = _HostFieldReplacer(self.host_chain).visit(node)
        return ast.Call(
            name="arrayExists",
            args=[ast.Lambda(args=[_HOST_LAMBDA_ARG], expr=predicate), ast.Field(chain=self.session_hosts_chain)],
        )

    def visit_and(self, node: ast.And) -> ast.And:
        # The host filters match against every host of the session, and the other filters match the one value the row
        # stores for the session. Live requires one event to match all of them. So a session that viewed host A from
        # one country and host B from another can match "host B and the first country", which live excludes. Only
        # sessions with more than one host and a second value of a per-event dimension (mostly viewport and geoip)
        # are affected, and only bounce rate and duration, because the counts come from the stats table.
        host_exprs = [expr for expr in node.exprs if self._host_only(expr)]
        other_exprs = [self.visit(expr) for expr in node.exprs if not self._host_only(expr)]
        if not host_exprs:
            return ast.And(exprs=other_exprs)
        combined = host_exprs[0] if len(host_exprs) == 1 else ast.And(exprs=host_exprs)
        return ast.And(exprs=[*other_exprs, self._match_any_host(combined)])

    def visit_or(self, node: ast.Or) -> ast.Expr:
        if self._host_only(node):
            return self._match_any_host(node)
        return super().visit_or(node)

    def visit_not(self, node: ast.Not) -> ast.Expr:
        if self._host_only(node):
            return self._match_any_host(node)
        return super().visit_not(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        if self._references_host(node):
            return self._match_any_host(node)
        return super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if self._host_only(node):
            return self._match_any_host(node)
        return super().visit_call(node)
