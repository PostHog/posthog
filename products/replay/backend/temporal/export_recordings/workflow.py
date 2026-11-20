import asyncio
import dataclasses
from datetime import date, timedelta

from temporalio import common, workflow

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


def shard_plan(date_from: str, date_to: str, shards_per_day: int) -> list[tuple[str, int]]:
    """Every (day, shard) pair, oldest day first, so the sessions closest to expiry go first."""
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    days = [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]
    return [(day, shard) for day in days for shard in range(shards_per_day)]


@workflow.defn(name="export-recordings")
class ExportRecordingsWorkflow(PostHogWorkflow):
    """Exports a team's recordings to the customer's S3 bucket, one file per session."""

    inputs_cls = ExportRecordingsInput

    @workflow.run
    async def run(self, input: ExportRecordingsInput) -> ExportTotals:
        started_at = input.started_at or workflow.now().isoformat()
        plan = shard_plan(input.date_from, input.date_to, input.shards_per_day)
        batch = plan[input.next_shard : input.next_shard + MAX_SHARDS_PER_RUN]
        semaphore = asyncio.Semaphore(input.max_parallel_shards)

        async def run_shard(day: str, shard: int) -> ExportTotals:
            async with semaphore:
                return await workflow.execute_activity(
                    export_shard,
                    ExportShardInput(
                        team_id=input.team_id,
                        destination=input.destination,
                        run_id=input.run_id,
                        day=day,
                        shard=shard,
                        shards_per_day=input.shards_per_day,
                        session_ids_key=input.session_ids_key,
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

        totals = input.totals
        for result in await asyncio.gather(*(run_shard(day, shard) for day, shard in batch)):
            totals = totals.add(result)

        next_shard = input.next_shard + len(batch)
        if next_shard < len(plan):
            workflow.continue_as_new(
                dataclasses.replace(input, next_shard=next_shard, totals=totals, started_at=started_at)
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
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=5),
        )
        return totals
