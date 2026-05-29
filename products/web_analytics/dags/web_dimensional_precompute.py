"""Scheduled population of the fixed-dimension web precompute tables.

This job drives the precomputation framework: for each selected team it calls
`ensure_*_dimensional_precomputed` over a rolling 90-day window, and the
framework splits that into daily jobs, tracks them in Postgres
(`PreaggregationJob`) and only (re)computes windows whose jobs have expired. So
the heavy raw-table scan happens on a schedule for a known audience rather than
lazily on every user query, while re-runs are cheap because already-fresh
windows are skipped.

Rollout is intentionally decoupled from the v2 pre-aggregation pipeline and its
team selection: the audience is an explicit allowlist from the
`WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS` env var (comma-separated team IDs). Unset
or empty means the job is a no-op, so it ships dark and is opt-in per team — we
turn it on for a couple of internal teams first to compare against v2 before
widening. There is no dependency on the v2 team-selection dictionary or flag.

The write path is not yet wired into any query runner — this job only populates
the tables (so the new output can be compared with v2's side by side).
"""

import os
from datetime import UTC, datetime, timedelta

import dagster
import structlog
from prometheus_client import Counter

from posthog.dags.common import JobOwners
from posthog.models import Team

from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)
from products.web_analytics.dags.web_preaggregated import skip_on_kill_switch
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)

# Rolling window kept warm. Matches the lazy precompute MAX_PRECOMPUTE_DAYS so a
# later read path can serve any sub-window without falling back to raw tables.
PRECOMPUTE_WINDOW_DAYS = 90

# Comma-separated team IDs to precompute. Empty/unset → the job is a no-op.
SELECTED_TEAM_IDS_ENV_VAR = "WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS"


def get_selected_team_ids() -> list[int]:
    """Parse the team allowlist from the env var. Invalid/blank entries are skipped."""
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR, "")
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


WEB_DIMENSIONAL_PRECOMPUTE_TEAM_DONE = Counter(
    "web_dimensional_precompute_team_done_total",
    "Teams whose dimensional precompute window was ensured, by table.",
    ["table"],
)
WEB_DIMENSIONAL_PRECOMPUTE_TEAM_FAILED = Counter(
    "web_dimensional_precompute_team_failed_total",
    "Teams whose dimensional precompute failed, by table and exception type.",
    ["table", "error_type"],
)


def _ensure_for_team(context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime) -> int:
    """Ensure both dimensional tables for one team. Returns the count of failures.

    Failures per table are caught so one broken team or table doesn't poison the
    rest of the run; the framework already inserts only the windows it needs.
    """
    failures = 0
    for table_label, ensure_fn in (
        ("web_stats_dimensional_preaggregated", ensure_web_stats_dimensional_precomputed),
        ("web_bounces_dimensional_preaggregated", ensure_web_bounces_dimensional_precomputed),
    ):
        try:
            ensure_fn(team, start, end)
            WEB_DIMENSIONAL_PRECOMPUTE_TEAM_DONE.labels(table=table_label).inc()
        except Exception as exc:
            WEB_DIMENSIONAL_PRECOMPUTE_TEAM_FAILED.labels(table=table_label, error_type=type(exc).__name__).inc()
            context.log.exception(f"web_dimensional_precompute_failed team={team.pk} table={table_label}")
            failures += 1
    return failures


@dagster.op
def ensure_web_dimensional_precompute_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Drive `ensure_*_dimensional_precomputed` over the rolling window for each selected team."""
    end = datetime.now(UTC)
    start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)

    team_ids = get_selected_team_ids()
    context.log.info(f"web_dimensional_precompute_start teams={len(team_ids)} window=[{start}, {end})")
    if not team_ids:
        context.log.info(f"web_dimensional_precompute_noop ({SELECTED_TEAM_IDS_ENV_VAR} is empty)")
        result = {"teams": 0, "failures": 0}
        context.add_output_metadata(result)
        return result

    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}

    failures = 0
    processed = 0
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"web_dimensional_precompute_team_missing team_id={team_id}")
            continue
        failures += _ensure_for_team(context, team, start, end)
        processed += 1

    context.log.info(f"web_dimensional_precompute_complete teams={processed} failures={failures}")
    result = {"teams": processed, "failures": failures}
    context.add_output_metadata(result)
    return result


@dagster.job(
    description=(
        f"Populates the fixed-dimension web precompute tables (web_stats_dimensional_preaggregated / "
        f"web_bounces_dimensional_preaggregated) over the trailing {PRECOMPUTE_WINDOW_DAYS} days for the teams in "
        f"the {SELECTED_TEAM_IDS_ENV_VAR} allowlist, by driving the precomputation framework's ensure_precomputed. "
        f"No-op when the allowlist is empty. Re-runs only recompute windows whose jobs have expired."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
    },
)
def web_dimensional_precompute_job():
    ensure_web_dimensional_precompute_op()


@dagster.schedule(
    # Hourly. Recent windows carry a short TTL (see DIMENSIONAL_TTL_SECONDS), so an
    # hourly cadence keeps today fresh; older windows are computed once and skipped.
    cron_schedule="20 * * * *",
    job=web_dimensional_precompute_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
@skip_on_kill_switch
def web_dimensional_precompute_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> "dagster.RunRequest | dagster.SkipReason":
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason
    return dagster.RunRequest()
