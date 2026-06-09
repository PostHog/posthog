"""
Daily Dagster job that marks `Team.ingested_production_event` for teams
whose recent traffic crosses the production-traffic criterion.

The criterion and the row-marking transition live in
`posthog/models/team/production_event_activation.py` (they're plain Python
helpers, tested in isolation). This file just orchestrates them: a single
op fans out unflagged team IDs into batches, each batch evaluates +
marks under a multiprocess executor, and an aggregate op emits run-level
counts as Dagster metadata.

Replaces the previous Celery beat task — Dagster gives us per-run metadata
(teams evaluated / qualifying / marked) and per-batch retry isolation, both
of which the Celery version lacked.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.db import connections

import dagster

from posthog.dags.common import JobOwners
from posthog.exceptions_capture import capture_exception
from posthog.models.team.production_event_activation import (
    DISTINCT_USERS_THRESHOLD,
    SWEEP_BATCH_SIZE,
    WINDOW_DAYS,
    evaluate_and_mark_team_batch,
)
from posthog.models.team.team import Team


@dataclass(kw_only=True)
class TeamBatchResult:
    team_count: int
    qualifying: int
    marked: int


@dagster.op(out=dagster.DynamicOut(list[int]))
def get_teams_without_production_event_op(context: dagster.OpExecutionContext):
    """Pull every team still missing `ingested_production_event` and fan out as batches.

    Using `DynamicOut` so downstream `.map()` runs each batch as its own
    op invocation — gives us per-batch retry and parallel execution under
    the multiprocess executor.
    """
    candidate_ids = list(Team.objects.filter(ingested_production_event=False).values_list("id", flat=True))
    total = len(candidate_ids)
    batch_count = (total + SWEEP_BATCH_SIZE - 1) // SWEEP_BATCH_SIZE

    context.log.info(f"Found {total} unflagged teams, fanning out into {batch_count} batches of {SWEEP_BATCH_SIZE}")

    # `add_output_metadata` is not permitted on a `DynamicOut` op without a per-output
    # `mapping_key`. Run-level totals get surfaced by `summarize_run_op`.
    for index in range(0, total, SWEEP_BATCH_SIZE):
        batch = candidate_ids[index : index + SWEEP_BATCH_SIZE]
        yield dagster.DynamicOutput(batch, mapping_key=f"batch_{index // SWEEP_BATCH_SIZE}")


@dagster.op
def evaluate_and_mark_team_batch_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> TeamBatchResult:
    """Evaluate the criterion against this batch and mark qualifying teams.

    Failures here surface as Dagster retries on this single batch — the
    rest of the run keeps going.
    """
    try:
        qualifying, marked = evaluate_and_mark_team_batch(team_ids, now=datetime.now(tz=UTC))
        result = TeamBatchResult(team_count=len(team_ids), qualifying=qualifying, marked=marked)
        context.log.info(f"Batch of {result.team_count}: {result.qualifying} qualifying, {result.marked} marked")
        context.add_output_metadata(
            {
                "team_count": dagster.MetadataValue.int(result.team_count),
                "qualifying": dagster.MetadataValue.int(result.qualifying),
                "marked": dagster.MetadataValue.int(result.marked),
            }
        )
        return result
    except Exception as e:
        context.log.exception(f"Failed to evaluate batch of {len(team_ids)} teams")
        capture_exception(e, {"team": "team-growth", "team_count": len(team_ids)})
        raise
    finally:
        # Release per-connection buffers between batches to keep RSS flat across
        # many batches sharing one subprocess. Skipped under TEST because
        # `execute_in_process` shares the test's outer transactional connection.
        if not settings.TEST:
            connections.close_all()


@dagster.op
def summarize_run_op(
    context: dagster.OpExecutionContext,
    results: list[TeamBatchResult],
) -> None:
    """Roll up per-batch counts into a single run-level summary."""
    teams_evaluated = sum(r.team_count for r in results)
    teams_qualifying = sum(r.qualifying for r in results)
    teams_marked = sum(r.marked for r in results)

    context.log.info(f"Run complete: {teams_evaluated} evaluated, {teams_qualifying} qualifying, {teams_marked} marked")
    context.add_output_metadata(
        {
            "teams_evaluated": dagster.MetadataValue.int(teams_evaluated),
            "teams_qualifying": dagster.MetadataValue.int(teams_qualifying),
            "teams_marked": dagster.MetadataValue.int(teams_marked),
            "batches": dagster.MetadataValue.int(len(results)),
            "distinct_users_threshold": dagster.MetadataValue.int(DISTINCT_USERS_THRESHOLD),
            "window_days": dagster.MetadataValue.int(WINDOW_DAYS),
        }
    )


@dagster.job(
    description=(
        "Daily job that marks Team.ingested_production_event for teams whose recent "
        "traffic crosses the production-traffic criterion. Replaces the Celery sweep."
    ),
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 5}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def detect_first_team_production_event_job():
    batches = get_teams_without_production_event_op()
    results = batches.map(evaluate_and_mark_team_batch_op)
    summarize_run_op(results.collect())


detect_first_team_production_event_schedule = dagster.ScheduleDefinition(
    job=detect_first_team_production_event_job,
    cron_schedule="0 4 * * *",
    execution_timezone="UTC",
    name="detect_first_team_production_event_schedule",
)
