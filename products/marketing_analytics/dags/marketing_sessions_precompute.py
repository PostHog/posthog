"""Scheduled population of the marketing session-grain precompute table.

Rollout is an allowlist, not a flag: the table is only useful for teams whose windows this job keeps
warm, and a team outside it falls through to the live path. `MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS`
overrides the built-in list; set it empty to disable the job.
"""

import os
from datetime import UTC, datetime, timedelta

import dagster
import structlog
from prometheus_client import Counter

from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, chunk_ranges
from posthog.models import Team

from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    CHUNK_DAYS,
    ensure_marketing_sessions_precomputed,
)
from products.web_analytics.dags.web_preaggregated import skip_on_kill_switch
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)

PRECOMPUTE_WINDOW_DAYS = int(os.getenv("MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS", "90"))

# The team the attribution memory failures come from. Widen once the trial holds.
DEFAULT_ROLLOUT_TEAM_IDS = [2]

SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS"

MARKETING_SESSIONS_PRECOMPUTE_TEAM_DONE = Counter(
    "marketing_sessions_precompute_team_done_total",
    "Teams whose marketing session precompute window was ensured.",
)
MARKETING_SESSIONS_PRECOMPUTE_TEAM_FAILED = Counter(
    "marketing_sessions_precompute_team_failed_total",
    "Teams whose marketing session precompute failed, by exception type.",
    ["error_type"],
)


def get_selected_team_ids() -> list[int]:
    """The env var wins if set, even to empty. Self-hosted defaults to none, so the job never
    precomputes for unrelated teams that happen to share those IDs."""
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR)
    if raw is None:
        return list(DEFAULT_ROLLOUT_TEAM_IDS) if is_cloud() else []
    return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]


def _ensure_for_team(
    context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime, chunk_days: int
) -> int:
    """One bounded chunk at a time, so no single INSERT scans the whole window. A failed chunk is
    caught so it does not poison the rest; already-fresh chunks cost a Postgres check."""
    failures = 0
    for chunk_start, chunk_end in chunk_ranges(start, end, chunk_days):
        try:
            ensure_marketing_sessions_precomputed(team, chunk_start, chunk_end)
            MARKETING_SESSIONS_PRECOMPUTE_TEAM_DONE.inc()
        except Exception as exc:
            MARKETING_SESSIONS_PRECOMPUTE_TEAM_FAILED.labels(error_type=type(exc).__name__).inc()
            context.log.exception(
                f"marketing_sessions_precompute_failed team={team.pk} chunk=[{chunk_start}, {chunk_end})"
            )
            failures += 1
    return failures


@dagster.op
def ensure_marketing_sessions_precompute_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    end = datetime.now(UTC)
    start = end - timedelta(days=PRECOMPUTE_WINDOW_DAYS)

    team_ids = get_selected_team_ids()
    context.log.info(
        f"marketing_sessions_precompute_start teams={len(team_ids)} window=[{start}, {end}) chunk_days={CHUNK_DAYS}"
    )
    if not team_ids:
        context.log.info(f"marketing_sessions_precompute_noop ({SELECTED_TEAM_IDS_ENV_VAR} is empty)")
        result = {"teams": 0, "failures": 0}
        context.add_output_metadata(result)
        return result

    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}

    failures = 0
    processed = 0
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"marketing_sessions_precompute_team_missing team_id={team_id}")
            continue
        failures += _ensure_for_team(context, team, start, end, CHUNK_DAYS)
        processed += 1

    context.log.info(f"marketing_sessions_precompute_complete teams={processed} failures={failures}")
    result = {"teams": processed, "failures": failures}
    context.add_output_metadata(result)
    return result


@dagster.job(
    description=(
        f"Populates marketing_sessions_dimensional_preaggregated over the trailing "
        f"{PRECOMPUTE_WINDOW_DAYS} days for the teams in the {SELECTED_TEAM_IDS_ENV_VAR} allowlist. "
        f"No-op when the allowlist is empty."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
    },
)
def marketing_sessions_precompute_job():
    ensure_marketing_sessions_precompute_op()


@dagster.schedule(
    cron_schedule="35 * * * *",
    job=marketing_sessions_precompute_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
@skip_on_kill_switch
def marketing_sessions_precompute_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> "dagster.RunRequest | dagster.SkipReason":
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason
    return dagster.RunRequest()
