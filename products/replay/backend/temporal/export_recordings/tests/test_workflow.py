import uuid

import pytest
from unittest.mock import patch

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.replay.backend.temporal.export_recordings import workflow
from products.replay.backend.temporal.export_recordings.quote import QuoteUsage, price
from products.replay.backend.temporal.export_recordings.types import (
    ExportDestination,
    ExportRecordingsInput,
    ExportShardInput,
    ExportTotals,
    WriteSummaryInput,
)


async def run_export(
    failing_shard: tuple[str, int] | None = None, only_shards: tuple[str, ...] | None = None
) -> tuple[list[tuple[str, int]], list[WriteSummaryInput], ExportTotals | Exception]:
    started: list[tuple[str, int]] = []
    summaries: list[WriteSummaryInput] = []

    @activity.defn(name="export_shard")
    async def fake_export_shard(input: ExportShardInput) -> ExportTotals:
        started.append((input.day, input.shard))
        if (input.day, input.shard) == failing_shard:
            raise ApplicationError("bucket unreachable", non_retryable=True)
        return ExportTotals(exported=2, missing=1, bytes=100)

    @activity.defn(name="write_summary")
    async def fake_write_summary(input: WriteSummaryInput) -> None:
        summaries.append(input)

    task_queue = str(uuid.uuid4())
    result: ExportTotals | Exception
    with patch.object(workflow, "MAX_SHARDS_PER_RUN", 3):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[workflow.ExportRecordingsWorkflow],
                activities=[fake_export_shard, fake_write_summary],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                try:
                    result = await env.client.execute_workflow(
                        "export-recordings",
                        ExportRecordingsInput(
                            team_id=1,
                            destination=ExportDestination(integration_id=1, bucket="b", region="us-east-1", prefix="p"),
                            quote_id="q",
                            run_id="r",
                            date_from="2026-01-30",
                            date_to="2026-02-01",
                            session_ids_prefix=None,
                            quoted_at="2026-02-02T00:00:00+00:00",
                            shards_per_day=2,
                            max_parallel_shards=1,
                            only_shards=only_shards,
                        ),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        result_type=ExportTotals,
                    )
                except WorkflowFailureError as e:
                    result = e
    return started, summaries, result


@pytest.mark.asyncio
async def test_runs_every_shard_oldest_day_first_across_continue_as_new() -> None:
    started, summaries, totals = await run_export()

    days = ["2026-01-30", "2026-01-31", "2026-02-01"]
    assert started == [(day, shard) for day in days for shard in range(2)]
    assert totals == ExportTotals(exported=12, missing=6, bytes=600)
    assert [(s.totals, s.failed_shards) for s in summaries] == [(totals, ())]


@pytest.mark.asyncio
async def test_a_failed_shard_keeps_the_other_shards_and_fails_the_run_after_the_summary() -> None:
    # The failed shard is in the first run, so the failure has to survive continue-as-new.
    started, summaries, result = await run_export(failing_shard=("2026-01-30", 1))

    assert len(started) == 6
    assert [(s.totals, s.failed_shards) for s in summaries] == [
        (ExportTotals(exported=10, missing=5, bytes=500), ("2026-01-30:1",))
    ]
    assert isinstance(result, WorkflowFailureError)


@pytest.mark.asyncio
async def test_only_shards_runs_just_those_shards() -> None:
    started, _, _ = await run_export(only_shards=("2026-01-31:1",))

    assert started == [("2026-01-31", 1)]


@pytest.mark.parametrize("cross_region,transfer_usd", [(False, 0.0), (True, 40.0)])
def test_price_charges_glacier_blocks_at_the_glacier_rates(cross_region: bool, transfer_usd: float) -> None:
    usage = QuoteUsage(
        sessions=10,
        blocks=2_000_000,
        bytes=2_000_000_000_000,
        glacier_blocks=1_000_000,
        glacier_bytes=1_000_000_000_000,
    )

    cost = price(usage, max_parallel_shards=10, cross_region=cross_region)

    assert (cost.standard_gets_usd, cost.glacier_ir_gets_usd, cost.glacier_ir_retrieval_usd, cost.transfer_usd) == (
        0.4,
        10.0,
        30.0,
        transfer_usd,
    )
    assert cost.total_usd == round(0.4 + 10.0 + 30.0 + transfer_usd + cost.compute_usd, 2)
