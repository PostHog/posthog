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

Gating mirrors the read path exactly. Touchpoints + conversions are warmed only when the team's
`marketing-analytics-precomputation` flag is on (the same flag `_should_use_precompute` checks) and the
team has conversion goals; costs only when `marketing-analytics-costs-precomputation` is on. Warming a
table the read won't consult would be wasted ClickHouse work, so both are evaluated from the same
`MarketingAnalyticsConfig.from_team` the runners use. The materialization INSERT is printed userless in
both paths, so a warmed job is byte-identical to the one a real read would create — same query hash,
same job, no poisoning and no access-control bypass.

Rollout mirrors the web dimensional precompute job: the audience is a small built-in list on PostHog
Cloud (`DEFAULT_ROLLOUT_TEAM_IDS`), fully overridable via the `MARKETING_PRECOMPUTE_TEAM_IDS` env var
(comma-separated team IDs; set it to empty to disable). Self-hosted defaults to no teams.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial

import dagster
import structlog
from prometheus_client import Counter

from posthog.schema import MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, check_for_concurrent_runs, chunk_ranges
from posthog.models import Team
from posthog.models.team.team import DEFAULT_CURRENCY
from posthog.settings import TEST

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
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
    COSTS_PRECOMPUTE_TTL_SECONDS,
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

# Built-in rollout audience used when the env var is unset: PostHog's internal dogfood project.
# Applied on PostHog Cloud only (see get_selected_team_ids).
DEFAULT_ROLLOUT_TEAM_IDS = [2]

# Comma-separated team IDs to warm. Overrides DEFAULT_ROLLOUT_TEAM_IDS; set to empty to disable.
SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_IDS"

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


def get_selected_team_ids() -> list[int]:
    """Resolve the team allowlist.

    The env var wins if set (even to empty): a comma-separated list, blank/invalid entries skipped.
    If unset, fall back to DEFAULT_ROLLOUT_TEAM_IDS — but only on PostHog Cloud; self-hosted defaults
    to none so the job never warms unrelated teams that happen to share those IDs.
    """
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR)
    if raw is None:
        return list(DEFAULT_ROLLOUT_TEAM_IDS) if is_cloud() else []
    return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]


def _ensure_chunks(
    context: dagster.OpExecutionContext,
    team: Team,
    table: LazyComputationTable,
    build_insert_query: Callable[[], ast.SelectQuery | None],
    ttl_seconds: dict[str, int],
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
    start: datetime,
    end: datetime,
    chunk_days: int,
) -> tuple[int, int]:
    """Warm the per-goal conversions table over [start, end] (no attribution backfill — the conversion
    event itself must fall in-range). One lazy job per precomputable goal; ineligible goals are skipped
    with the same rule the read path uses (is_goal_precomputable). Returns (goals_warmed, failures).
    """
    goals = convert_team_conversion_goals_to_objects(team.marketing_analytics_config.conversion_goals, team.pk)
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


def _ensure_costs_for_team(
    context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime, chunk_days: int
) -> tuple[int, int]:
    """Warm the per-source cost table at every supported grain over [start, end] (no attribution
    backfill). The database is built userless with warehouse access control bypassed — the materialization
    INSERT is printed userless anyway, so this yields the maximal (and read-identical) adapter set without
    a requesting user. Returns (source_grain_pairs_warmed, failures).
    """
    # Every cost adapter (native, external, self-managed) needs at least one warehouse table — the factory
    # filters DataWarehouseTable by the hogql database's table names. With none, discovery yields nothing,
    # so skip before paying the ~550ms Database.create_for. Safe superset: having tables doesn't guarantee
    # a valid marketing source, but having none guarantees there isn't one.
    if not DataWarehouseTable.objects.filter(team_id=team.pk, deleted=False).exists():
        return 0, 0

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
                COSTS_PRECOMPUTE_TTL_SECONDS,
                start,
                end,
                chunk_days,
            )
    return warmed, failures


@dagster.op
def ensure_marketing_precompute_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Drive ensure_precomputed for the marketing precompute tables over the rolling window per team.

    Per team, gated on the same flags the read path checks: touchpoints + conversions when the
    conversion precompute flag is on and the team has goals; costs when the costs precompute flag is on.
    Each team's setup and each warming block is isolated: an unexpected error (e.g. a broken warehouse
    source failing Database.create_for) is logged and counted, never aborting the rest of the allowlist.
    """
    # Tag every ClickHouse query this op drives (schema introspection during Database.create_for and the
    # materialization INSERTs) so warmer-driven load is attributable in query_log, distinct from the
    # on-read materialization the query runner triggers. The read path is tagged via its runner context.
    tag_queries(product=Product.MARKETING_ANALYTICS, feature=Feature.CACHE_WARMUP)

    end = datetime.now(UTC)
    team_ids = get_selected_team_ids()
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

    failures = 0
    processed = 0
    conversion_teams = 0
    costs_teams = 0
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"marketing_precompute_team_missing team_id={team_id}")
            continue
        processed += 1

        try:
            # from_team evaluates both precompute flags once (cached on the team instance) — the same
            # evaluation the runners use, so the warmer and read path always agree on what to precompute.
            config = MarketingAnalyticsConfig.from_team(team)
            ma_config = team.marketing_analytics_config
        except Exception:
            MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="setup").inc()
            context.log.exception(f"marketing_precompute_setup_failed team={team_id}")
            failures += 1
            continue

        # Conversions and costs are independent products behind independent flags — isolate each so a
        # failure in one (e.g. Database.create_for on a broken warehouse source) still lets the other run.
        if config.conversion_goal_precomputation_enabled and ma_config.conversion_goals:
            try:
                attribution_window_days = ma_config.attribution_window_days or DEFAULT_ATTRIBUTION_WINDOW_DAYS
                # Reach back far enough that a read with up to PRECOMPUTE_WINDOW_DAYS of lookback is fully
                # covered including its touchpoints attribution backfill ([date_from - attribution_window, date_to]).
                tp_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS + attribution_window_days)
                failures += _ensure_touchpoints_for_team(context, team, tp_start, end, PRECOMPUTE_CHUNK_DAYS)
                # Conversions need no attribution backfill — the conversion event must fall in the query range.
                # Goals that aren't precomputable (non-Events/Actions, schema remaps, person/cohort filters) are
                # skipped inside; a team can warm touchpoints but no conversions if no goal qualifies.
                conv_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)
                _goals_warmed, conv_failures = _ensure_conversions_for_team(
                    context, team, config, conv_start, end, PRECOMPUTE_CHUNK_DAYS
                )
                failures += conv_failures
                conversion_teams += 1
            except Exception:
                MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="conversions").inc()
                context.log.exception(f"marketing_precompute_conversions_failed team={team_id}")
                failures += 1

        if config.costs_precomputation_enabled:
            try:
                costs_start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)
                sources_warmed, costs_failures = _ensure_costs_for_team(
                    context, team, costs_start, end, PRECOMPUTE_CHUNK_DAYS
                )
                failures += costs_failures
                if sources_warmed:
                    costs_teams += 1
            except Exception:
                MARKETING_PRECOMPUTE_TEAM_FAILED.labels(stage="costs").inc()
                context.log.exception(f"marketing_precompute_costs_failed team={team_id}")
                failures += 1

    context.log.info(
        f"marketing_precompute_complete teams={processed} conversion_teams={conversion_teams} "
        f"costs_teams={costs_teams} failures={failures}"
    )
    result = {
        "teams": processed,
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
        f"days for the teams in the {SELECTED_TEAM_IDS_ENV_VAR} allowlist, gated per table on the same "
        f"precompute flags the read path checks, by driving the lazy-computation framework's "
        f"ensure_precomputed. No-op when the allowlist is empty. Re-runs only recompute expired windows."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
    },
)
def marketing_precompute_job():
    ensure_marketing_precompute_op()


@dagster.schedule(
    # Hourly. Recent windows carry a short TTL (see PRECOMPUTE_TTL_SECONDS), so an hourly cadence
    # keeps today fresh; older windows are computed once and skipped. Offset from the web jobs.
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
