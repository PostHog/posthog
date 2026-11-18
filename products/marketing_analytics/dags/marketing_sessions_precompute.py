"""Scheduled population of the marketing session-grain precompute table.

The table is only useful for teams whose windows this job keeps warm. Configure
`MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS` to enable the job; an empty or unset value disables it.
"""

import os
from datetime import UTC, datetime

import dagster
import structlog
from prometheus_client import Counter

from posthog.dags.common import JobOwners, check_for_concurrent_runs, chunk_ranges, skip_on_kill_switch
from posthog.models import Team

from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    CHUNK_DAYS,
    PRECOMPUTE_WINDOW_DAYS,
    ensure_marketing_sessions_precomputed,
    precompute_window_start,
)

logger = structlog.get_logger(__name__)


SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS"

MARKETING_SESSIONS_PRECOMPUTE_CHUNK_DONE = Counter(
    "marketing_sessions_precompute_chunk_done_total",
    "Daily chunks whose marketing session precompute window was ensured.",
)
MARKETING_SESSIONS_PRECOMPUTE_CHUNK_FAILED = Counter(
    "marketing_sessions_precompute_chunk_failed_total",
    "Daily chunks whose marketing session precompute failed, by error type.",
    ["error_type"],
)


def get_selected_team_ids() -> list[int]:
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR, "")
    return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]


def _ensure_for_team(
    context: dagster.OpExecutionContext, team: Team, start: datetime, end: datetime, chunk_days: int
) -> int:
    """Keep each failed chunk isolated so the rest of the team's history can still warm."""
    failures = 0
    for chunk_start, chunk_end in chunk_ranges(start, end, chunk_days):
        try:
            result = ensure_marketing_sessions_precomputed(team, chunk_start, chunk_end)
            # The executor reports a failed insert in the result rather than by raising, so a chunk
            # that never materialized would otherwise be counted as done.
            if not result.ready:
                MARKETING_SESSIONS_PRECOMPUTE_CHUNK_FAILED.labels(
                    error_type="memory_exceeded" if result.memory_exceeded else "not_ready"
                ).inc()
                context.log.error(
                    f"marketing_sessions_precompute_not_ready team={team.pk} "
                    f"chunk=[{chunk_start}, {chunk_end}) errors={result.errors}"
                )
                failures += 1
                continue
            MARKETING_SESSIONS_PRECOMPUTE_CHUNK_DONE.inc()
        except Exception as exc:
            MARKETING_SESSIONS_PRECOMPUTE_CHUNK_FAILED.labels(error_type=type(exc).__name__).inc()
            context.log.exception(
                f"marketing_sessions_precompute_failed team={team.pk} chunk=[{chunk_start}, {chunk_end})"
            )
            failures += 1
    return failures


@dagster.op
def ensure_marketing_sessions_precompute_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    now = datetime.now(UTC)

    team_ids = get_selected_team_ids()
    context.log.info(
        f"marketing_sessions_precompute_start teams={len(team_ids)} display_days={PRECOMPUTE_WINDOW_DAYS} now={now} chunk_days={CHUNK_DAYS}"
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
        start = precompute_window_start(team, now)
        # Attribution reads include the full local day, which can cross into the next UTC day.
        end = (
            now.astimezone(team.timezone_info)
            .replace(hour=23, minute=59, second=59, microsecond=999999)
            .astimezone(UTC)
        )
        failures += _ensure_for_team(context, team, start, end, CHUNK_DAYS)
        processed += 1

    context.log.info(f"marketing_sessions_precompute_complete teams={processed} failures={failures}")
    result = {"teams": processed, "failures": failures}
    context.add_output_metadata(result)
    return result


@dagster.job(
    description=(
        f"Populates web_sessions_dimensional_preaggregated over the trailing "
        f"{PRECOMPUTE_WINDOW_DAYS} display days plus team attribution lookback and session reachback for the teams in the {SELECTED_TEAM_IDS_ENV_VAR} allowlist. "
        f"No-op when the allowlist is empty."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(2 * 60 * 60),
    },
)
def marketing_sessions_precompute_job() -> None:
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
    skip_reason = check_for_concurrent_runs(context, tags={})
    if skip_reason:
        return skip_reason
    return dagster.RunRequest()
