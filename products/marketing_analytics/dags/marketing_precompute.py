"""Scheduled warming of the marketing analytics precompute tables.

Marketing analytics' first page load is dominated by cold reads the lazy-computation framework serves
from three config-agnostic / per-goal / per-source preaggregated tables — but only once the rows are
there. Nothing populates them ahead of time, so the first visitor after a cache miss pays the full
materialization inline (`ensure_precomputed` runs the INSERT synchronously on the request thread):

  * `marketing_touchpoints_preaggregated` — pageview/UTM side of conversion-goal attribution. Scans
    `$pageview` events over the range *plus* the attribution window (up to 90 extra days). Config-
    agnostic: one warmed window serves every goal / attribution mode for a team.
  * `marketing_conversions_preaggregated` — the conversion-event side. Per goal (the query embeds the
    goal's event/action + filters + math), independent of attribution mode/window.
  * `marketing_costs_preaggregated` — native ad-spend cost rows. Per source, materialized at each
    supported grain (campaign/ad_group/ad); replaces a cold S3 read of the platform tables.

This job moves that cost off the request path: per team it drives `ensure_precomputed` over a rolling
window so a later read is a cheap warm hit. Re-runs are cheap — already-fresh windows are skipped via
the framework's Postgres job tracking.

Touchpoints + conversions are warmed for every team with a conversion goal, independent of the
`marketing-analytics-precomputation` read flag: the precompute is populated ahead of the flag so it can
be validated against live (see verify_marketing_precompute_parity) and the flag flip is then instant and
safe. Costs stay gated on `marketing-analytics-costs-precomputation` — cost reads fall back to S3, so
warming them before that flag is on is wasted work. The materialization INSERT is printed userless, so a
warmed job is byte-identical to the one a real read would create — same query hash, same job, no
poisoning and no access-control bypass.

Reads are precompute-only, so the audience is every team that has a conversion goal AND has opened
marketing analytics recently (query_log), keeping the rolling warm set to the active population. Cold
teams drop out and are warmed on-demand on their next visit. The `MARKETING_PRECOMPUTE_TEAM_IDS` env
var overrides the audience (comma-separated team IDs; set it to empty to disable warming entirely);
`MARKETING_PRECOMPUTE_ACTIVE_DAYS` tunes the activity window.
"""

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import NamedTuple

from django.db import connections

import dagster
import structlog
from prometheus_client import Counter

from posthog.schema import MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level, sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dags.common import JobOwners, check_for_concurrent_runs, chunk_ranges
from posthog.models import Team
from posthog.models.team.team import DEFAULT_CURRENCY
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig
from posthog.settings import TEST

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    TtlSchedule,
    ensure_precomputed,
)
from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import (
    PRECOMPUTE_TTL_SECONDS,
    ConversionGoalProcessor,
    build_touchpoints_precompute_query,
)
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner import (
    costs_precompute_ttl_schedule,
)
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig
from products.marketing_analytics.backend.hogql_queries.utils import convert_team_conversion_goals_to_objects
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

logger = structlog.get_logger(__name__)

# Rolling window of user-facing lookback kept warm. A read for [date_from, date_to] ensures touchpoints
# over [date_from - attribution_window, date_to], so the effective touchpoints scan reaches back
# WINDOW + attribution_window days (see _ensure_touchpoints_for_team). Conversions and costs span the
# plain window (no attribution backfill).
PRECOMPUTE_WINDOW_DAYS = int(os.getenv("MARKETING_PRECOMPUTE_WINDOW_DAYS", "90"))

# Each ensure_precomputed call covers at most this many days. The framework merges a fully-missing
# range into ONE INSERT, so without chunking a cold backfill would scan the whole window in a single
# query — the real memory risk for a high-volume team. Chunking bounds each INSERT's scan; combined
# with the job's max_runtime and ensure_precomputed's idempotency, a cold backfill self-paces across
# runs. Defaults to 1 so every INSERT scans a single day.
PRECOMPUTE_CHUNK_DAYS = int(os.getenv("MARKETING_PRECOMPUTE_CHUNK_DAYS", "1"))

# Fallback attribution window when a team has no explicit config. Matches the model default and the
# 1–90 validation bound (TeamMarketingAnalyticsConfig.attribution_window_days).
DEFAULT_ATTRIBUTION_WINDOW_DAYS = 90

# Cost rows are materialized at each grain a source supports; the read side picks the matching grain per
# drill-down (a campaign-stats row is not the roll-up of its ads). Warming all three keeps every drill-
# down warm — campaign serves CHANNEL/SOURCE/CAMPAIGN/UTM, ad_group/ad serve their own levels.
COST_MATERIALIZATION_GRAINS = (
    MarketingAnalyticsDrillDownLevel.CAMPAIGN,
    MarketingAnalyticsDrillDownLevel.AD_GROUP,
    MarketingAnalyticsDrillDownLevel.AD,
)

# Comma-separated team IDs to warm. When set, it wins (an explicit override / kill switch: set it to
# empty to disable warming entirely). When unset, the warmer discovers teams — see get_selected_team_ids.
SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_IDS"

# Only keep teams warm while they are actually using marketing analytics. A team that has not opened it
# within this window drops out of the rolling warm set; its next visit reads not-ready and triggers a
# one-off background warm. This bounds the fleet to the active population instead of every team that ever
# set a goal. query_log retention caps the effective lookback (~14 days), which is the low end of the range
# we want anyway.
ACTIVE_DAYS_ENV_VAR = "MARKETING_PRECOMPUTE_ACTIVE_DAYS"
DEFAULT_ACTIVE_DAYS = 30

# Teams warmed in parallel per run. Warming is I/O-bound (ClickHouse INSERTs), so threads overlap the
# waits; the ceiling keeps concurrent ClickHouse load and DB connections bounded. Tunable per environment.
TEAM_CONCURRENCY_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_CONCURRENCY"
DEFAULT_TEAM_CONCURRENCY = 8

_TOUCHPOINTS_TABLE_LABEL = LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED.value
_CONVERSIONS_TABLE_LABEL = LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED.value
_COSTS_TABLE_LABEL = LazyComputationTable.MARKETING_COSTS_PREAGGREGATED.value

MARKETING_PRECOMPUTE_CHUNK_DONE = Counter(
    "marketing_analytics_precompute_chunk_done_total",
    "Marketing precompute chunks ensured warm, by table.",
    ["table"],
)
MARKETING_PRECOMPUTE_CHUNK_FAILED = Counter(
    "marketing_analytics_precompute_chunk_failed_total",
    "Marketing precompute chunks that failed, by table and error type.",
    ["table", "error_type"],
)
MARKETING_PRECOMPUTE_TEAM_FAILED = Counter(
    "marketing_analytics_precompute_team_failed_total",
    "Per-team warming aborted by an unexpected setup/orchestration error, by stage.",
    ["stage"],
)


def _recently_active_team_ids(days: int) -> set[int] | None:
    """Teams that ran a marketing-analytics query within `days`, from query_log. None on failure.

    None means "couldn't tell" (query_log unavailable / errored) and the caller fails open to warming
    every team with a goal, so a transient failure over-warms for one run rather than starving the fleet.
    """
    try:
        # Match on the query_type tag in log_comment (the intended API, as the web warmer does), not a
        # substring of the SQL text — the tag is stable, the annotation format is not.
        rows = sync_execute(
            """
            SELECT DISTINCT JSONExtractInt(log_comment, 'team_id') AS team_id
            FROM clusterAllReplicas(posthog, system, query_log)
            WHERE type != 'QueryStart'
              AND event_time > now() - toIntervalDay(%(days)s)
              AND JSONExtractString(log_comment, 'query_type') IN (
                'marketing_analytics_table_query',
                'marketing_analytics_aggregated_query',
                'non_integrated_conversions_table_query'
              )
              AND team_id > 0
            """,
            {"days": days},
        )
        return {int(row[0]) for row in rows}
    except Exception:
        logger.exception("marketing_precompute_active_teams_query_failed")
        return None


def get_selected_team_ids() -> list[int]:
    """Resolve which teams to warm.

    Reads are precompute-only, so a team that uses marketing analytics must be kept warm or its
    conversion-goal tiles read not-ready. The default audience is every team that both has a conversion
    goal (`TeamMarketingAnalyticsConfig`) and has opened marketing analytics recently (query_log) — this
    keeps the rolling warm set to the active population. Cold teams are warmed on-demand on their next
    visit instead.

    The env var still wins when set (even to empty): a comma-separated override / kill switch, blank or
    invalid entries skipped. Per-team flag and eligibility checks inside the warmer still gate what is
    actually materialized.
    """
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR)
    if raw is not None:
        return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]

    goal_team_ids = set(
        TeamMarketingAnalyticsConfig.objects.exclude(_conversion_goals=[])
        .exclude(_conversion_goals__isnull=True)
        .values_list("team_id", flat=True)
    )
    if not goal_team_ids:
        return []

    active_days = int(os.getenv(ACTIVE_DAYS_ENV_VAR, str(DEFAULT_ACTIVE_DAYS)))
    active_team_ids = _recently_active_team_ids(active_days)
    if active_team_ids is None:
        # Fail open: couldn't determine activity, so warm every goal team this run rather than starve.
        return sorted(goal_team_ids)
    return sorted(goal_team_ids & active_team_ids)


def _ensure_chunks(
    context: dagster.OpExecutionContext,
    team: Team,
    table: LazyComputationTable,
    build_insert_query: Callable[[], ast.SelectQuery | None],
    ttl_seconds: dict[str, int] | TtlSchedule,
    start: datetime,
    end: datetime,
    chunk_days: int,
) -> int:
    """Drive ensure_precomputed for one (team, table, query) across the window, one bounded chunk at a
    time. `build_insert_query` is called fresh per chunk (the executor resolves the time-window
    placeholders in place). Failures per chunk are isolated so one bad chunk doesn't poison the rest;
    already-fresh chunks are cheap PG checks with no INSERT. Returns the failure count.
    """
    table_label = table.value
    failures = 0
    for chunk_start, chunk_end in chunk_ranges(start, end, chunk_days):
        insert_query = build_insert_query()
        if insert_query is None:
            continue  # source can't materialize this chunk (deterministic) — nothing to warm
        try:
            result = ensure_precomputed(
                team=team,
                insert_query=insert_query,
                time_range_start=chunk_start,
                time_range_end=chunk_end,
                ttl_seconds=ttl_seconds,
                table=table,
            )
        except Exception:
            MARKETING_PRECOMPUTE_CHUNK_FAILED.labels(table=table_label, error_type="exception").inc()
            context.log.exception(
                f"marketing_precompute_failed team={team.pk} table={table_label} chunk=[{chunk_start}, {chunk_end})"
            )
            failures += 1
            continue

        if result.ready:
            MARKETING_PRECOMPUTE_CHUNK_DONE.labels(table=table_label).inc()
        else:
            MARKETING_PRECOMPUTE_CHUNK_FAILED.labels(table=table_label, error_type="not_ready").inc()
            context.log.warning(
                f"marketing_precompute_not_ready team={team.pk} table={table_label} "
                f"chunk=[{chunk_start}, {chunk_end}) errors={result.errors}"
            )
            failures += 1
    return failures


def _ensure_touchpoints_for_team(
    context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime, chunk_days: int
) -> int:
    """Warm the config-agnostic touchpoints table over [start, end] (start already reaches back past the
    attribution window). One warmed window serves every conversion goal / attribution mode.
    """
    return _ensure_chunks(
        context,
        team,
        LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
        build_touchpoints_precompute_query,
        PRECOMPUTE_TTL_SECONDS,
        start,
        end,
        chunk_days,
    )


def _ensure_conversions_for_team(
    context: dagster.OpExecutionContext,
    team: Team,
    config: MarketingAnalyticsConfig,
    goals: list,
    start: datetime,
    end: datetime,
    chunk_days: int,
) -> tuple[int, int]:
    """Warm the per-goal conversions table over [start, end] (no attribution backfill — the conversion
    event itself must fall in-range). One lazy job per precomputable goal; ineligible goals are skipped
    with the same rule the read path uses (is_goal_precomputable). `goals` are converted on the main
    thread (see _plan_team) so this does no Django ORM. Returns (goals_warmed, failures).
    """
    goals_warmed = 0
    failures = 0
    for index, goal in enumerate(goals):
        processor = ConversionGoalProcessor(goal=goal, index=index, team=team, config=config, user=None)
        if not processor.is_goal_precomputable():
            continue
        goals_warmed += 1
        failures += _ensure_chunks(
            context,
            team,
            LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED,
            processor.build_conversions_precompute_query,
            PRECOMPUTE_TTL_SECONDS,
            start,
            end,
            chunk_days,
        )
    return goals_warmed, failures


def _team_has_cost_sources(team: Team) -> bool:
    """Cheap indexed check for the prerequisite every cost adapter (native/external/self-managed) shares:
    at least one warehouse table. A safe superset — having tables doesn't guarantee a valid marketing
    source, but having none guarantees there isn't one, so we skip the ~550ms Database.create_for.
    """
    return DataWarehouseTable.objects.filter(team_id=team.pk, deleted=False).exists()


def _ensure_costs_for_team(
    context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime, chunk_days: int
) -> tuple[int, int]:
    """Warm the per-source cost table at every supported grain over [start, end] (no attribution
    backfill). The database is built userless with warehouse access control bypassed — the materialization
    INSERT is printed userless anyway, so this yields the maximal (and read-identical) adapter set without
    a requesting user. Caller gates on _team_has_cost_sources, so at least one warehouse table exists.
    Returns (source_grain_pairs_warmed, failures).
    """
    # Database.create_for is ~550ms; build once and share across grains/sources for this team.
    database = Database.create_for(
        team=team,
        modifiers=create_default_modifiers_for_team(team),
        bypass_warehouse_access_control=True,
    )
    base_currency = team.base_currency or DEFAULT_CURRENCY
    warmed = 0
    failures = 0
    for grain in COST_MATERIALIZATION_GRAINS:
        ctx = QueryContext(
            date_range=None,  # materialization filters on time_window placeholders, not the range
            team=team,
            base_currency=base_currency,
            drill_down_level=grain,
            database=database,
        )
        factory = MarketingSourceFactory(context=ctx)
        adapters = [a for a in factory.get_valid_adapters(factory.create_adapters()) if a.supports_level(grain)]
        for adapter in adapters:
            source_id = adapter.get_source_id()
            # A source that can't build a materialization query (e.g. missing table) does so deterministically
            # regardless of window — probe once, skip the whole source rather than every chunk.
            if adapter.build_materialization_query(source_id) is None:
                context.log.info(
                    f"marketing_precompute_skip_source team={team.pk} table={_COSTS_TABLE_LABEL} "
                    f"grain={grain.value} source_id={source_id} reason=unmaterializable"
                )
                continue
            warmed += 1
            failures += _ensure_chunks(
                context,
                team,
                LazyComputationTable.MARKETING_COSTS_PREAGGREGATED,
                partial(adapter.build_materialization_query, source_id),
                costs_precompute_ttl_schedule(team),
                start,
                end,
                chunk_days,
            )
    return warmed, failures


class _TeamWarmPlan(NamedTuple):
    """What to warm for one team, decided on the main thread so worker threads do no Django ORM reads.

    `from_team` primes the flag + `marketing_analytics_config` caches on the `team` instance, so the
    worker's downstream accesses (e.g. reading conversion goals) are cache hits, not queries that would
    deadlock against the test transaction — and in production keep the parallel section to ClickHouse.
    """

    team: Team
    config: MarketingAnalyticsConfig
    conversion_goals: list
    attribution_window_days: int
    warm_costs: bool

    @property
    def warm_conversions(self) -> bool:
        return bool(self.conversion_goals)


class _WarmCounts(NamedTuple):
    """Per-team warming outcome: teams whose conversion / cost block completed, and per-chunk failures."""

    conversion_teams: int
    costs_teams: int
    failures: int


def _plan_team(team: Team) -> _TeamWarmPlan | None:
    """Main-thread setup: read config, flags and goals so worker threads do no Django ORM. None on failure.

    Every DB read the warming does happens here — flag evaluation, the conversion goals, and the
    cost-source check — so a worker thread never queries Postgres (which would deadlock against the test
    transaction and, in production, serialise the parallel section behind DB round-trips).

    Conversion warming is deliberately NOT gated on the `marketing-analytics-precomputation` read flag: we
    populate the precompute for every team with a goal so it can be validated (see the parity command)
    while reads still serve live, then flip the read flag per team knowing the data is already warm. Costs
    stay gated on their own flag — cost reads fall back to S3, so warming them before that flag is on is
    wasted work.
    """
    try:
        config = MarketingAnalyticsConfig.from_team(team)
        ma_config = team.marketing_analytics_config
        conversion_goals = (
            convert_team_conversion_goals_to_objects(ma_config.conversion_goals, team.pk)
            if ma_config.conversion_goals
            else []
        )
        return _TeamWarmPlan(
            team=team,
            config=config,
            conversion_goals=conversion_goals,
            attribution_window_days=ma_config.attribution_window_days or DEFAULT_ATTRIBUTION_WINDOW_DAYS,
            warm_costs=bool(config.costs_precomputation_enabled and _team_has_cost_sources(team)),
        )
    except Exception:
        MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="setup").inc()
        logger.exception("marketing_precompute_setup_failed", team_id=team.pk)
        return None


def _warm_team(context: dagster.OpExecutionContext, plan: _TeamWarmPlan, end: datetime) -> _WarmCounts:
    """Warm one planned team's precomputes over the rolling window.

    Returns (conversion_teams, costs_teams, failures) increments. Runs in a worker thread of the op's
    pool, so it: re-tags for query_log attribution (threads don't inherit the op's contextvars), reads no
    Django ORM (the plan primed every cache on the main thread), contains every error (a raise would abort
    sibling teams still in `pool.map`), and closes its thread-local connections on the way out.
    """
    # Pool threads don't inherit the op's query tags, so re-tag here — otherwise this team's warm INSERTs
    # and schema introspection would be un-attributable in query_log.
    tag_queries(product=Product.MARKETING_ANALYTICS, feature=Feature.CACHE_WARMUP)
    team = plan.team
    conversion_teams = 0
    costs_teams = 0
    failures = 0
    try:
        # Conversions and costs are independent products behind independent flags — isolate each so a
        # failure in one (e.g. Database.create_for on a broken warehouse source) still lets the other run.
        if plan.warm_conversions:
            try:
                # Reach back far enough that a read with up to PRECOMPUTE_WINDOW_DAYS of lookback is fully
                # covered including its touchpoints attribution backfill ([date_from - attribution_window, date_to]).
                tp_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS + plan.attribution_window_days)
                failures += _ensure_touchpoints_for_team(context, team, tp_start, end, PRECOMPUTE_CHUNK_DAYS)
                # Conversions need no attribution backfill — the conversion event must fall in the query range.
                # Goals that aren't precomputable (non-Events/Actions, schema remaps, person/cohort filters) are
                # skipped inside; a team can warm touchpoints but no conversions if no goal qualifies.
                conv_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)
                _goals_warmed, conv_failures = _ensure_conversions_for_team(
                    context, team, plan.config, plan.conversion_goals, conv_start, end, PRECOMPUTE_CHUNK_DAYS
                )
                failures += conv_failures
                conversion_teams += 1
            except Exception:
                MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="conversions").inc()
                logger.exception("marketing_precompute_conversions_failed", team_id=team.pk)
                failures += 1

        if plan.warm_costs:
            try:
                costs_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)
                _sources_warmed, costs_failures = _ensure_costs_for_team(
                    context, team, costs_start, end, PRECOMPUTE_CHUNK_DAYS
                )
                failures += costs_failures
                costs_teams += 1  # after the block, mirroring conversion_teams: not counted if it raised
            except Exception:
                MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="costs").inc()
                logger.exception("marketing_precompute_costs_failed", team_id=team.pk)
                failures += 1
    finally:
        connections.close_all()
    return _WarmCounts(conversion_teams, costs_teams, failures)


@dagster.op
def ensure_marketing_precompute_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Drive ensure_precomputed for the marketing precompute tables over the rolling window per team.

    Teams are warmed in parallel (`_warm_team` in a thread pool, `MARKETING_PRECOMPUTE_TEAM_CONCURRENCY`
    workers), since warming is I/O-bound on ClickHouse and the active fleet is hundreds of teams. Each
    team is gated on the same flags the read path checks: touchpoints + conversions when the conversion
    precompute flag is on and the team has goals; costs when the costs precompute flag is on and the team
    has warehouse tables. Every team, and each warming block within it, is isolated — one failure never
    aborts the rest.

    `conversion_teams` / `costs_teams` count teams whose block ran to completion without an unexpected
    error (flag on + its raw material present — goals / warehouse tables), symmetric to each other. They
    are not success counts: per-chunk outcomes live in `failures` and the MARKETING_PRECOMPUTE_CHUNK_*
    metrics (a block can complete having warmed zero chunks, e.g. all goals ineligible).
    """
    # Tag the op thread too (workers re-tag themselves). Keeps any op-thread ClickHouse work attributable.
    tag_queries(product=Product.MARKETING_ANALYTICS, feature=Feature.CACHE_WARMUP)

    end = datetime.now(UTC)
    team_ids = list(dict.fromkeys(get_selected_team_ids()))  # dedupe so a repeated id doesn't warm twice
    context.log.info(
        f"marketing_precompute_start teams={len(team_ids)} window_days={PRECOMPUTE_WINDOW_DAYS} "
        f"chunk_days={PRECOMPUTE_CHUNK_DAYS}"
    )
    if not team_ids:
        context.log.info(f"marketing_precompute_noop ({SELECTED_TEAM_IDS_ENV_VAR} is empty)")
        result = {"teams": 0, "conversion_teams": 0, "costs_teams": 0, "failures": 0}
        context.add_output_metadata(result)
        return result

    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}
    teams = [teams_by_id[team_id] for team_id in team_ids if team_id in teams_by_id]
    if len(teams) != len(team_ids):
        context.log.warning(f"marketing_precompute_teams_missing count={len(team_ids) - len(teams)}")

    # Plan on the main thread: evaluate flags + prerequisites and prime each team's caches, so the worker
    # threads do only ClickHouse warming (no Django ORM). Setup failures are counted here.
    failures = 0
    plans: list[_TeamWarmPlan] = []
    for team in teams:
        plan = _plan_team(team)
        if plan is None:
            failures += 1
        else:
            plans.append(plan)

    concurrency = int(os.getenv(TEAM_CONCURRENCY_ENV_VAR, str(DEFAULT_TEAM_CONCURRENCY)))
    conversion_teams = 0
    costs_teams = 0
    if plans:
        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(plans))), thread_name_prefix="ma_warm") as pool:
            for conv_inc, costs_inc, fail_inc in pool.map(lambda plan: _warm_team(context, plan, end), plans):
                conversion_teams += conv_inc
                costs_teams += costs_inc
                failures += fail_inc

    context.log.info(
        f"marketing_precompute_complete teams={len(teams)} conversion_teams={conversion_teams} "
        f"costs_teams={costs_teams} failures={failures}"
    )
    result = {
        "teams": len(teams),
        "conversion_teams": conversion_teams,
        "costs_teams": costs_teams,
        "failures": failures,
    }
    context.add_output_metadata(result)
    return result


@dagster.job(
    description=(
        f"Warms the marketing analytics precompute tables ({_TOUCHPOINTS_TABLE_LABEL}, "
        f"{_CONVERSIONS_TABLE_LABEL}, {_COSTS_TABLE_LABEL}) over the trailing {PRECOMPUTE_WINDOW_DAYS} "
        f"days for every recently-active team with a conversion goal (or the {SELECTED_TEAM_IDS_ENV_VAR} "
        f"override), warming teams in parallel and gating per table on the same precompute flags the read "
        f"path checks, by driving the lazy-computation framework's ensure_precomputed. Re-runs only "
        f"recompute expired windows."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
    },
)
def marketing_precompute_job():
    ensure_marketing_precompute_op()


@dagster.schedule(
    # Hourly. Keeps the expensive part warm — the older windows / attribution backfill, computed once
    # then skipped. The today-slice carries a deliberately short TTL (PRECOMPUTE_TTL_SECONDS "0d" = 15m,
    # data still changing), so it can still be stale between hourly runs and recompute inline on read;
    # that slice is one day, not the backfill, so the cost is bounded. Offset from the web jobs.
    cron_schedule="35 * * * *",
    job=marketing_precompute_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def marketing_precompute_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> "dagster.RunRequest | dagster.SkipReason":
    if not TEST:
        kill_switch_level = get_kill_switch_level()
        if kill_switch_level != KillSwitchLevel.OFF:
            context.log.info(f"Skipping due to ClickHouse kill switch: {kill_switch_level}")
            return dagster.SkipReason(f"ClickHouse kill switch is enabled ({kill_switch_level})")

    skip_reason = check_for_concurrent_runs(context, tags={})
    if skip_reason:
        return skip_reason
    return dagster.RunRequest()
