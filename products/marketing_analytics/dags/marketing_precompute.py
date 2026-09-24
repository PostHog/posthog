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

The audience is `MARKETING_PRECOMPUTE_TEAM_IDS`: comma-separated team IDs, empty to disable warming, or
`auto` to warm every team that has a conversion goal AND has opened marketing analytics recently
(query_log). Unset, it warms the teams with a conversion goal and the read flag on, on PostHog Cloud
only. `MARKETING_PRECOMPUTE_ACTIVE_DAYS` tunes the `auto` activity window.
"""

import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from posthog.cloud_utils import is_cloud
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

# Comma-separated team IDs to warm, empty to disable warming, or `auto` to discover the audience.
SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_IDS"
AUTO_AUDIENCE = "auto"

# Only keep teams warm while they are actually using marketing analytics. A team that has not opened it
# within this window drops out of the rolling warm set; its next visit reads not-ready and triggers a
# one-off background warm. This bounds the fleet to the active population instead of every team that ever
# set a goal. query_log retention caps the effective lookback (~14 days), which is the low end of the range
# we want anyway.
ACTIVE_DAYS_ENV_VAR = "MARKETING_PRECOMPUTE_ACTIVE_DAYS"
DEFAULT_ACTIVE_DAYS = 30
ACTIVE_TEAMS_QUERY_TIMEOUT_SECONDS = 60

# Teams warmed in parallel per shard. Threads overlap the ClickHouse INSERT waits; shards x this bounds the
# concurrent INSERTs and DB connections across the run. Tunable per environment.
TEAM_CONCURRENCY_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_CONCURRENCY"
DEFAULT_TEAM_CONCURRENCY = 4

# Processes the job fans teams out into. Each shard prints HogQL on its own core; the run pod requests
# 6 CPUs, so more shards than that only contend for cores.
SHARDS_ENV_VAR = "MARKETING_PRECOMPUTE_SHARDS"
DEFAULT_SHARDS = 6
MAX_SHARDS = 16

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

    None means "couldn't tell" (query_log unavailable / errored) and the caller skips the run. Warming
    every goal team instead would turn one transient failure into a fleet-wide backfill.
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
                'marketing_analytics_aggregated_query'
              )
              AND team_id > 0
            """,
            {"days": days},
            settings={"max_execution_time": ACTIVE_TEAMS_QUERY_TIMEOUT_SECONDS},
        )
        return {int(row[0]) for row in rows}
    except Exception:
        logger.exception("marketing_precompute_active_teams_query_failed")
        return None


def _goal_team_ids() -> set[int]:
    return set(
        TeamMarketingAnalyticsConfig.objects.exclude(_conversion_goals=[])
        .exclude(_conversion_goals__isnull=True)
        .values_list("team_id", flat=True)
    )


def _read_flag_team_ids() -> list[int]:
    """Goal teams that have the `marketing-analytics-precomputation` read flag on.

    Only that flag is evaluated, and without an exposure event: this hourly scan picks an audience, so
    it must not look like every goal team read marketing analytics behind the flag.
    """
    teams = Team.objects.filter(pk__in=_goal_team_ids()).select_related("organization")
    return sorted(
        team.pk for team in teams if MarketingAnalyticsConfig.conversion_precompute_enabled_without_exposure(team)
    )


def get_selected_team_ids() -> list[int]:
    """Resolve which teams to warm.

    Unset, it warms every team that has a conversion goal and the `marketing-analytics-precomputation`
    read flag on. Those reads are precompute-only, so a flagged team the warmer skips reads not-ready.
    Cloud only: self-hosted has no flag rollout to follow. Set, the env var wins (even when empty, as a
    kill switch): a comma-separated list with blank or invalid entries skipped.

    `auto` warms every team that both has a conversion goal (`TeamMarketingAnalyticsConfig`) and has
    opened marketing analytics recently (query_log), which keeps the rolling warm set to the active
    population. Cold teams are warmed on-demand on their next visit instead.
    """
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR)
    if raw is None:
        return _read_flag_team_ids() if is_cloud() else []
    if raw.strip().lower() != AUTO_AUDIENCE:
        return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]

    goal_team_ids = _goal_team_ids()
    if not goal_team_ids:
        return []

    active_days = int(os.getenv(ACTIVE_DAYS_ENV_VAR, str(DEFAULT_ACTIVE_DAYS)))
    active_team_ids = _recently_active_team_ids(active_days)
    if active_team_ids is None:
        return []
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
    database: Database | None = None,
) -> int:
    """Drive ensure_precomputed for one (team, table, query) across the window, one bounded chunk at a
    time. `build_insert_query` is called fresh per chunk (the executor resolves the time-window
    placeholders in place). Failures per chunk are isolated so one bad chunk doesn't poison the rest;
    already-fresh chunks are cheap PG checks with no INSERT. Returns the failure count.
    """
    table_label = table.value
    failures = 0
    chunks = 0
    build_seconds = 0.0
    ensure_seconds = 0.0
    started = time.monotonic()
    for chunk_start, chunk_end in chunk_ranges(start, end, chunk_days):
        chunks += 1
        build_started = time.monotonic()
        insert_query = build_insert_query()
        build_seconds += time.monotonic() - build_started
        if insert_query is None:
            continue  # source can't materialize this chunk (deterministic) — nothing to warm
        ensure_started = time.monotonic()
        try:
            result = ensure_precomputed(
                team=team,
                insert_query=insert_query,
                time_range_start=chunk_start,
                time_range_end=chunk_end,
                ttl_seconds=ttl_seconds,
                table=table,
                database=database,
            )
        except Exception:
            ensure_seconds += time.monotonic() - ensure_started
            MARKETING_PRECOMPUTE_CHUNK_FAILED.labels(table=table_label, error_type="exception").inc()
            context.log.exception(
                f"marketing_precompute_failed team={team.pk} table={table_label} chunk=[{chunk_start}, {chunk_end})"
            )
            failures += 1
            continue
        ensure_seconds += time.monotonic() - ensure_started

        if result.ready:
            MARKETING_PRECOMPUTE_CHUNK_DONE.labels(table=table_label).inc()
        else:
            MARKETING_PRECOMPUTE_CHUNK_FAILED.labels(table=table_label, error_type="not_ready").inc()
            context.log.warning(
                f"marketing_precompute_not_ready team={team.pk} table={table_label} "
                f"chunk=[{chunk_start}, {chunk_end}) errors={result.errors}"
            )
            failures += 1
    context.log.info(
        f"marketing_precompute_table_timing team={team.pk} table={table_label} chunks={chunks} "
        f"failures={failures} wall_ms={round((time.monotonic() - started) * 1000)} "
        f"build_query_ms={round(build_seconds * 1000)} ensure_ms={round(ensure_seconds * 1000)}"
    )
    return failures


def _ensure_touchpoints_for_team(
    context: dagster.OpExecutionContext,
    team: Team,
    filter_test_accounts: bool,
    start: datetime,
    end: datetime,
    chunk_days: int,
    database: Database | None = None,
) -> int:
    """Warm the goal-agnostic touchpoints table over [start, end] (start already reaches back past the
    attribution window). One warmed window serves every conversion goal / attribution mode.

    Test-account filtering is the one thing that splits it: the filter is baked into the insert query,
    which the framework hashes for the job key, so warming the wrong variant leaves every read to
    materialize inline. The team's own setting is what the dashboard sends, so warm that one. It is read
    by `_plan_team` on the main thread, because reading the team extension here would query Postgres from
    a worker thread.
    """
    return _ensure_chunks(
        context,
        team,
        LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
        partial(build_touchpoints_precompute_query, team, filter_test_accounts),
        PRECOMPUTE_TTL_SECONDS,
        start,
        end,
        chunk_days,
        database,
    )


def _ensure_conversions_for_team(
    context: dagster.OpExecutionContext,
    team: Team,
    config: MarketingAnalyticsConfig,
    goals: list,
    filter_test_accounts: bool,
    start: datetime,
    end: datetime,
    chunk_days: int,
    database: Database | None = None,
) -> tuple[int, int]:
    """Warm the per-goal conversions table over [start, end] (no attribution backfill — the conversion
    event itself must fall in-range). One lazy job per precomputable goal; ineligible goals are skipped
    with the same rule the read path uses (is_goal_precomputable). `goals` are converted on the main
    thread (see _plan_team) so this does no Django ORM. Returns (goals_warmed, failures).
    """
    goals_warmed = 0
    failures = 0
    for index, goal in enumerate(goals):
        processor = ConversionGoalProcessor(
            goal=goal,
            index=index,
            team=team,
            config=config,
            user=None,
            filter_test_accounts=filter_test_accounts,
        )
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
            database,
        )
    return goals_warmed, failures


def _build_team_database(team: Team) -> Database:
    """The HogQL database every INSERT for this team prints against.

    Built userless with warehouse access control bypassed and the default modifiers, which is what the
    executor builds per INSERT when it gets none. Building it once per team instead of once per bucket
    removes most of the warmer's CPU, which the process otherwise spends rebuilding the same schema.
    """
    return Database.create_for(
        team=team,
        modifiers=create_default_modifiers_for_team(team),
        bypass_warehouse_access_control=True,
    )


def _team_has_cost_sources(team: Team) -> bool:
    """Cheap indexed check for the prerequisite every cost adapter (native/external/self-managed) shares:
    at least one warehouse table. A safe superset — having tables doesn't guarantee a valid marketing
    source, but having none guarantees there isn't one, so we skip the ~550ms Database.create_for.
    """
    return DataWarehouseTable.objects.filter(team_id=team.pk, deleted=False).exists()


def _ensure_costs_for_team(
    context: dagster.OpExecutionContext,
    team: Team,
    start: datetime,
    end: datetime,
    chunk_days: int,
    database: Database | None = None,
) -> tuple[int, int]:
    """Warm the per-source cost table at every supported grain over [start, end] (no attribution
    backfill). The database is built userless with warehouse access control bypassed — the materialization
    INSERT is printed userless anyway, so this yields the maximal (and read-identical) adapter set without
    a requesting user. Caller gates on _team_has_cost_sources, so at least one warehouse table exists.
    Returns (source_grain_pairs_warmed, failures).
    """
    # Database.create_for is ~550ms; build once and share across grains/sources for this team.
    if database is None:
        database = _build_team_database(team)
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
                database,
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
    filter_test_accounts: bool
    warm_costs: bool
    database: Database | None = None

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
            filter_test_accounts=bool(ma_config.filter_test_accounts),
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
    started = time.monotonic()
    try:
        # Conversions and costs are independent products behind independent flags — isolate each so a
        # failure in one (e.g. Database.create_for on a broken warehouse source) still lets the other run.
        if plan.warm_conversions:
            try:
                # Reach back far enough that a read with up to PRECOMPUTE_WINDOW_DAYS of lookback is fully
                # covered including its touchpoints attribution backfill ([date_from - attribution_window, date_to]).
                tp_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS + plan.attribution_window_days)
                failures += _ensure_touchpoints_for_team(
                    context, team, plan.filter_test_accounts, tp_start, end, PRECOMPUTE_CHUNK_DAYS, plan.database
                )
                # Conversions need no attribution backfill — the conversion event must fall in the query range.
                # Goals that aren't precomputable (non-Events/Actions, schema remaps, person/cohort filters) are
                # skipped inside; a team can warm touchpoints but no conversions if no goal qualifies.
                conv_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)
                _goals_warmed, conv_failures = _ensure_conversions_for_team(
                    context,
                    team,
                    plan.config,
                    plan.conversion_goals,
                    plan.filter_test_accounts,
                    conv_start,
                    end,
                    PRECOMPUTE_CHUNK_DAYS,
                    plan.database,
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
                    context, team, costs_start, end, PRECOMPUTE_CHUNK_DAYS, plan.database
                )
                failures += costs_failures
                costs_teams += 1  # after the block, mirroring conversion_teams: not counted if it raised
            except Exception:
                MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="costs").inc()
                logger.exception("marketing_precompute_costs_failed", team_id=team.pk)
                failures += 1
    finally:
        connections.close_all()
    context.log.info(
        f"marketing_precompute_team_timing team={team.pk} goals={len(plan.conversion_goals)} "
        f"warm_costs={plan.warm_costs} failures={failures} wall_ms={round((time.monotonic() - started) * 1000)}"
    )
    return _WarmCounts(conversion_teams, costs_teams, failures)


def _empty_result() -> dict[str, int]:
    return {"teams": 0, "conversion_teams": 0, "costs_teams": 0, "failures": 0}


def _warm_teams(context: dagster.OpExecutionContext, team_ids: list[int], end: datetime) -> dict[str, int]:
    """Warm the marketing precompute tables over the rolling window for `team_ids`.

    Teams are warmed in parallel (`_warm_team` in a thread pool, `MARKETING_PRECOMPUTE_TEAM_CONCURRENCY`
    workers), which overlaps the ClickHouse INSERTs. Printing each INSERT is CPU-bound Python, so real
    parallelism across teams comes from running shards in separate processes (see
    `warm_marketing_precompute_shard_op`). Each team warms touchpoints + conversions when it has
    conversion goals; costs stay gated on the costs precompute flag plus the team having warehouse tables.
    Every team, and each warming block within it, is isolated — one failure never aborts the rest.

    `conversion_teams` / `costs_teams` count teams whose block ran to completion without an unexpected
    error (its raw material present — goals / warehouse tables), symmetric to each other. They
    are not success counts: per-chunk outcomes live in `failures` and the MARKETING_PRECOMPUTE_CHUNK_*
    metrics (a block can complete having warmed zero chunks, e.g. all goals ineligible).
    """
    # Tag the op thread too (workers re-tag themselves). Keeps any op-thread ClickHouse work attributable.
    tag_queries(product=Product.MARKETING_ANALYTICS, feature=Feature.CACHE_WARMUP)
    if not team_ids:
        return _empty_result()

    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}
    teams = [teams_by_id[team_id] for team_id in team_ids if team_id in teams_by_id]
    if len(teams) != len(team_ids):
        context.log.warning(f"marketing_precompute_teams_missing count={len(team_ids) - len(teams)}")

    # Plan on the main thread: evaluate flags + prerequisites and prime each team's caches, so the worker
    # threads do only ClickHouse warming (no Django ORM). Setup failures are counted here.
    failures = 0
    plans: list[_TeamWarmPlan] = []
    plan_started = time.monotonic()
    for team in teams:
        plan = _plan_team(team)
        if plan is None:
            failures += 1
        else:
            plans.append(plan)

    concurrency = max(1, int(os.getenv(TEAM_CONCURRENCY_ENV_VAR, str(DEFAULT_TEAM_CONCURRENCY))))
    context.log.info(
        f"marketing_precompute_planned plans={len(plans)} concurrency={concurrency} "
        f"plan_ms={round((time.monotonic() - plan_started) * 1000)}"
    )
    conversion_teams = 0
    costs_teams = 0
    done = 0
    warm_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="ma_warm") as pool:
        # Batches of `concurrency`: each team's database is built on the main thread (it reads Postgres,
        # which worker threads must not) just before its batch runs, so only one batch of databases is
        # held in memory at a time.
        for batch_start in range(0, len(plans), concurrency):
            batch: list[_TeamWarmPlan] = []
            db_started = time.monotonic()
            for plan in plans[batch_start : batch_start + concurrency]:
                if not (plan.warm_conversions or plan.warm_costs):
                    batch.append(plan)  # nothing to warm, so skip the database build
                    continue
                try:
                    batch.append(plan._replace(database=_build_team_database(plan.team)))
                except Exception:
                    MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="database").inc()
                    logger.exception("marketing_precompute_database_failed", team_id=plan.team.pk)
                    failures += 1
            context.log.info(
                f"marketing_precompute_databases_built teams={len(batch)} "
                f"ms={round((time.monotonic() - db_started) * 1000)}"
            )
            futures = [pool.submit(_warm_team, context, plan, end) for plan in batch]
            for future in as_completed(futures):
                conv_inc, costs_inc, fail_inc = future.result()
                conversion_teams += conv_inc
                costs_teams += costs_inc
                failures += fail_inc
                done += 1
                context.log.info(
                    f"marketing_precompute_progress done={done}/{len(plans)} "
                    f"elapsed_s={round(time.monotonic() - warm_started)}"
                )

    context.log.info(
        f"marketing_precompute_complete teams={len(teams)} conversion_teams={conversion_teams} "
        f"costs_teams={costs_teams} failures={failures}"
    )
    return {
        "teams": len(teams),
        "conversion_teams": conversion_teams,
        "costs_teams": costs_teams,
        "failures": failures,
    }


def warm_selected_teams(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Warm every selected team in this process. The job fans out instead; this is the single-process path."""
    return _warm_teams(context, list(dict.fromkeys(get_selected_team_ids())), datetime.now(UTC))


def _shard_count() -> int:
    return min(MAX_SHARDS, max(1, int(os.getenv(SHARDS_ENV_VAR, str(DEFAULT_SHARDS)))))


@dagster.op(out=dagster.DynamicOut(dict))
def split_marketing_precompute_teams_op(context: dagster.OpExecutionContext):
    """Select the teams to warm and fan them out into team-disjoint shards.

    Each shard becomes its own mapped op, a separate subprocess with its own GIL. Printing each INSERT is
    CPU-bound Python, so threads inside one process queue on the interpreter and real parallelism needs
    processes. Every shard shares one `end`, so all shards warm the same windows.
    """
    team_ids = list(dict.fromkeys(get_selected_team_ids()))  # dedupe so a repeated id doesn't warm twice
    shards = _shard_count()
    context.log.info(
        f"marketing_precompute_start teams={len(team_ids)} shards={shards} window_days={PRECOMPUTE_WINDOW_DAYS} "
        f"chunk_days={PRECOMPUTE_CHUNK_DAYS}"
    )
    if not team_ids:
        context.log.info(f"marketing_precompute_noop ({SELECTED_TEAM_IDS_ENV_VAR} is empty)")
        return
    end = datetime.now(UTC).isoformat()
    buckets: dict[int, list[int]] = {}
    for team_id in team_ids:
        buckets.setdefault(team_id % shards, []).append(team_id)
    for shard_index in sorted(buckets):
        yield dagster.DynamicOutput({"team_ids": buckets[shard_index], "end": end}, mapping_key=f"shard_{shard_index}")


@dagster.op
def warm_marketing_precompute_shard_op(context: dagster.OpExecutionContext, shard: dict) -> dict[str, int]:
    result = _warm_teams(context, shard["team_ids"], datetime.fromisoformat(shard["end"]))
    context.add_output_metadata(result)
    return result


@dagster.op
def summarize_marketing_precompute_op(context: dagster.OpExecutionContext, results: list[dict]) -> dict[str, int]:
    total = _empty_result()
    for result in results:
        for key in total:
            total[key] += result[key]
    context.log.info(
        f"marketing_precompute_summary shards={len(results)} teams={total['teams']} "
        f"conversion_teams={total['conversion_teams']} costs_teams={total['costs_teams']} "
        f"failures={total['failures']}"
    )
    context.add_output_metadata(total)
    return total


@dagster.job(
    description=(
        f"Warms the marketing analytics precompute tables ({_TOUCHPOINTS_TABLE_LABEL}, "
        f"{_CONVERSIONS_TABLE_LABEL}, {_COSTS_TABLE_LABEL}) over the trailing {PRECOMPUTE_WINDOW_DAYS} "
        f"days for the teams in the {SELECTED_TEAM_IDS_ENV_VAR} audience, fanning teams out across "
        f"processes and gating per table on the same precompute flags the read "
        f"path checks, by driving the lazy-computation framework's ensure_precomputed. Re-runs only "
        f"recompute expired windows."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
        # One subprocess per shard, each printing HogQL on its own core, so the run pod needs CPU for the
        # shards and memory for that many Django interpreters. Matches the web cache warming job.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"cpu": "6000m", "memory": "12Gi"},
                    "limits": {"memory": "12Gi"},
                }
            }
        },
    },
)
def marketing_precompute_job():
    summarize_marketing_precompute_op(
        split_marketing_precompute_teams_op().map(warm_marketing_precompute_shard_op).collect()
    )


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
