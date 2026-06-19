"""Scheduled warming of the marketing analytics touchpoints precompute table.

Marketing analytics' conversion-goal attribution is the heaviest part of the page's first
load: the live path scans `$pageview` events over the requested range *plus* the attribution
window (up to 90 extra days). The read path already knows how to serve that from the
config-agnostic `marketing_touchpoints_preaggregated` table via the lazy-computation
framework — but only if the rows are already there. Today nothing populates them ahead of
time, so the first visitor after a cache miss pays the full materialization cost inline
(`ensure_precomputed` runs the INSERT synchronously on the request thread).

This job moves that cost off the request path: for each selected team it drives
`ensure_precomputed` over a rolling window so a later read is a cheap warm hit. The touchpoints
table is config-agnostic and shared across every conversion goal / attribution mode for a team,
so one warmed window serves them all. Re-runs are cheap — already-fresh windows are skipped via
the framework's Postgres job tracking.

Rollout mirrors the web dimensional precompute job: the audience is a small built-in list on
PostHog Cloud (`DEFAULT_ROLLOUT_TEAM_IDS`), fully overridable via the
`MARKETING_PRECOMPUTE_TEAM_IDS` env var (comma-separated team IDs; set it to empty to disable).
Self-hosted defaults to no teams. The `marketing-analytics-precomputation` feature flag must be
enabled for the same teams — otherwise the read path won't consult the warmed table and the work
is wasted. Keep the allowlist and the flag audience in sync.
"""

import os
from datetime import UTC, datetime, timedelta

import dagster
import structlog
from prometheus_client import Counter

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, check_for_concurrent_runs, chunk_ranges
from posthog.models import Team
from posthog.settings import TEST

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import (
    PRECOMPUTE_TTL_SECONDS,
    build_touchpoints_precompute_query,
)

logger = structlog.get_logger(__name__)

# Rolling window of user-facing lookback kept warm. A read for [date_from, date_to] ensures
# touchpoints over [date_from - attribution_window, date_to], so the effective scan reaches back
# WINDOW + attribution_window days — see _ensure_touchpoints_for_team.
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

# Built-in rollout audience used when the env var is unset: PostHog's internal dogfood project.
# Applied on PostHog Cloud only (see get_selected_team_ids).
DEFAULT_ROLLOUT_TEAM_IDS = [2]

# Comma-separated team IDs to warm. Overrides DEFAULT_ROLLOUT_TEAM_IDS; set to empty to disable.
SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_IDS"

_TOUCHPOINTS_TABLE_LABEL = LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED.value

MARKETING_PRECOMPUTE_TEAM_DONE = Counter(
    "marketing_analytics_precompute_chunk_done_total",
    "Touchpoint precompute chunks ensured warm, by table.",
    ["table"],
)
MARKETING_PRECOMPUTE_TEAM_FAILED = Counter(
    "marketing_analytics_precompute_chunk_failed_total",
    "Touchpoint precompute chunks that failed, by table and error type.",
    ["table", "error_type"],
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


def _ensure_touchpoints_for_team(
    context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime, chunk_days: int
) -> int:
    """Ensure the touchpoints table for one team, one bounded chunk at a time.

    Each chunk is a separate ensure_precomputed call (one INSERT scanning at most `chunk_days` of
    raw pageviews), so no single query scans the whole window. Failures per chunk are caught so one
    bad chunk doesn't poison the rest; already-fresh chunks are cheap PG checks with no INSERT.
    """
    failures = 0
    for chunk_start, chunk_end in chunk_ranges(start, end, chunk_days):
        try:
            result = ensure_precomputed(
                team=team,
                # Build fresh per call — the executor resolves the time-window placeholders in place.
                insert_query=build_touchpoints_precompute_query(),
                time_range_start=chunk_start,
                time_range_end=chunk_end,
                ttl_seconds=PRECOMPUTE_TTL_SECONDS,
                table=LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
            )
        except Exception:
            MARKETING_PRECOMPUTE_TEAM_FAILED.labels(table=_TOUCHPOINTS_TABLE_LABEL, error_type="exception").inc()
            context.log.exception(f"marketing_precompute_failed team={team.pk} chunk=[{chunk_start}, {chunk_end})")
            failures += 1
            continue

        if result.ready:
            MARKETING_PRECOMPUTE_TEAM_DONE.labels(table=_TOUCHPOINTS_TABLE_LABEL).inc()
        else:
            MARKETING_PRECOMPUTE_TEAM_FAILED.labels(table=_TOUCHPOINTS_TABLE_LABEL, error_type="not_ready").inc()
            context.log.warning(
                f"marketing_precompute_not_ready team={team.pk} chunk=[{chunk_start}, {chunk_end}) "
                f"errors={result.errors}"
            )
            failures += 1
    return failures


@dagster.op
def ensure_marketing_precompute_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Drive `ensure_precomputed` for the touchpoints table over the rolling window per team.

    Teams with no conversion goals are skipped — nothing reads the touchpoints table for them, so
    warming would be wasted CH work.
    """
    end = datetime.now(UTC)
    team_ids = get_selected_team_ids()
    context.log.info(
        f"marketing_precompute_start teams={len(team_ids)} window_days={PRECOMPUTE_WINDOW_DAYS} "
        f"chunk_days={PRECOMPUTE_CHUNK_DAYS}"
    )
    if not team_ids:
        context.log.info(f"marketing_precompute_noop ({SELECTED_TEAM_IDS_ENV_VAR} is empty)")
        result = {"teams": 0, "skipped": 0, "failures": 0}
        context.add_output_metadata(result)
        return result

    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}

    failures = 0
    processed = 0
    skipped = 0
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"marketing_precompute_team_missing team_id={team_id}")
            continue

        ma_config = team.marketing_analytics_config
        if not ma_config.conversion_goals:
            context.log.info(f"marketing_precompute_skip team={team_id} reason=no_conversion_goals")
            skipped += 1
            continue

        attribution_window_days = ma_config.attribution_window_days or DEFAULT_ATTRIBUTION_WINDOW_DAYS
        # Reach back far enough that a read with up to PRECOMPUTE_WINDOW_DAYS of lookback is fully
        # covered including its attribution backfill ([date_from - attribution_window, date_to]).
        start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS + attribution_window_days)
        failures += _ensure_touchpoints_for_team(context, team, start, end, PRECOMPUTE_CHUNK_DAYS)
        processed += 1

    context.log.info(f"marketing_precompute_complete teams={processed} skipped={skipped} failures={failures}")
    result = {"teams": processed, "skipped": skipped, "failures": failures}
    context.add_output_metadata(result)
    return result


@dagster.job(
    description=(
        f"Warms the marketing analytics touchpoints precompute table "
        f"({_TOUCHPOINTS_TABLE_LABEL}) over the trailing {PRECOMPUTE_WINDOW_DAYS} days (+ each team's "
        f"attribution window) for the teams in the {SELECTED_TEAM_IDS_ENV_VAR} allowlist, by driving "
        f"the lazy-computation framework's ensure_precomputed. No-op when the allowlist is empty. "
        f"Re-runs only recompute windows whose jobs have expired."
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
