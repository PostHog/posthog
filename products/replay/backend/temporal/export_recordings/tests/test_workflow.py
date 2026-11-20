import uuid

import pytest
from unittest.mock import patch

import temporalio.worker
from temporalio import activity
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


@pytest.mark.asyncio
async def test_runs_every_shard_oldest_day_first_across_continue_as_new() -> None:
    started: list[tuple[str, int]] = []
    summaries: list[WriteSummaryInput] = []

    @activity.defn(name="export_shard")
    async def fake_export_shard(input: ExportShardInput) -> ExportTotals:
        started.append((input.day, input.shard))
        return ExportTotals(exported=2, missing=1, bytes=100)

    @activity.defn(name="write_summary")
    async def fake_write_summary(input: WriteSummaryInput) -> None:
        summaries.append(input)

    task_queue = str(uuid.uuid4())
    with patch.object(workflow, "MAX_SHARDS_PER_RUN", 3):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[workflow.ExportRecordingsWorkflow],
                activities=[fake_export_shard, fake_write_summary],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                totals = await env.client.execute_workflow(
                    "export-recordings",
                    ExportRecordingsInput(
                        team_id=1,
                        destination=ExportDestination(integration_id=1, bucket="b", region="us-east-1", prefix="p"),
                        quote_id="q",
                        run_id="r",
                        date_from="2026-01-30",
                        date_to="2026-02-01",
                        session_ids_key=None,
                        quoted_at="2026-02-02T00:00:00+00:00",
                        shards_per_day=2,
                        max_parallel_shards=1,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    result_type=ExportTotals,
                )

    days = ["2026-01-30", "2026-01-31", "2026-02-01"]
    assert started == [(day, shard) for day in days for shard in range(2)]
    assert totals == ExportTotals(exported=12, missing=6, bytes=600)
    assert [s.totals for s in summaries] == [totals]


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
