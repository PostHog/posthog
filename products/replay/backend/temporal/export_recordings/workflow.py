import asyncio
import dataclasses
from datetime import date, timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.replay.backend.temporal.export_recordings.activities import export_shard, write_summary
from products.replay.backend.temporal.export_recordings.types import (
    ExportRecordingsInput,
    ExportShardInput,
    ExportTotals,
    WriteSummaryInput,
)

# Keeps each run's history well under Temporal's event limit; longer exports continue as new.
MAX_SHARDS_PER_RUN = 2000


def shard_name(day: str, shard: int) -> str:
    return f"{day}:{shard}"


def shard_plan(input: ExportRecordingsInput) -> list[tuple[str, int]]:
    """Every (day, shard) pair to run, oldest day first, so the sessions closest to expiry go first."""
    first, last = date.fromisoformat(input.date_from), date.fromisoformat(input.date_to)
    days = [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]
    plan = [(day, shard) for day in days for shard in range(input.shards_per_day)]
    if input.only_shards is not None:
        plan = [(day, shard) for day, shard in plan if shard_name(day, shard) in input.only_shards]
    return plan


@workflow.defn(name="export-recordings")
class ExportRecordingsWorkflow(PostHogWorkflow):
    """Exports a team's recordings to the customer's S3 bucket, one file per session."""

    inputs_cls = ExportRecordingsInput

    @workflow.run
    async def run(self, input: ExportRecordingsInput) -> ExportTotals:
        started_at = input.started_at or workflow.now().isoformat()
        plan = shard_plan(input)
        batch = plan[input.next_shard : input.next_shard + MAX_SHARDS_PER_RUN]
        semaphore = asyncio.Semaphore(input.max_parallel_shards)

        async def run_shard(day: str, shard: int) -> ExportTotals | None:
            async with semaphore:
                try:
                    return await self._export_shard(input, day, shard)
                except ActivityError:
                    # One shard out of retries must not throw away the others' work. The summary lists it.
                    workflow.logger.warning("Export shard failed", extra={"day": day, "shard": shard})
                    return None

        totals = input.totals
        failed_shards = list(input.failed_shards)
        results = await asyncio.gather(*(run_shard(day, shard) for day, shard in batch))
        for (day, shard), result in zip(batch, results):
            if result is None:
                failed_shards.append(shard_name(day, shard))
            else:
                totals = totals.add(result)

        next_shard = input.next_shard + len(batch)
        if next_shard < len(plan):
            workflow.continue_as_new(
                dataclasses.replace(
                    input,
                    next_shard=next_shard,
                    totals=totals,
                    failed_shards=tuple(failed_shards),
                    started_at=started_at,
                )
            )

        await workflow.execute_activity(
            write_summary,
            WriteSummaryInput(
                team_id=input.team_id,
                destination=input.destination,
                quote_id=input.quote_id,
                run_id=input.run_id,
                shards_per_day=input.shards_per_day,
                started_at=started_at,
                totals=totals,
                failed_shards=tuple(failed_shards),
                complete=not failed_shards and input.only_shards is None,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=5),
        )
        if failed_shards:
            raise ApplicationError(
                f"{len(failed_shards)} shards failed: {','.join(failed_shards)}. Rerun them with --shards.",
                non_retryable=True,
            )
        return totals

    @staticmethod
    async def _export_shard(input: ExportRecordingsInput, day: str, shard: int) -> ExportTotals:
        return await workflow.execute_activity(
            export_shard,
            ExportShardInput(
                team_id=input.team_id,
                destination=input.destination,
                run_id=input.run_id,
                day=day,
                shard=shard,
                shards_per_day=input.shards_per_day,
                session_ids_prefix=input.session_ids_prefix,
                quoted_at=input.quoted_at,
            ),
            start_to_close_timeout=timedelta(hours=12),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=10,
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=10),
            ),
        )
