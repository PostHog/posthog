"""The spec registry is read only inside activities, so adding a sweep never changes the
command sequence an existing execution replays against.
"""

import typing
import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections
from posthog.utils import get_instance_region

from products.growth.backend.temporal.signup_enrichment import harmonic_status_poll, reenrichment
from products.growth.backend.temporal.signup_enrichment.sweep_types import (
    SweepBatchInputs,
    SweepInputs,
    SweepKind,
    SweepRunReport,
    SweepSelection,
    SweepSpec,
)

LOGGER = get_logger(__name__)

SWEEPS: dict[SweepKind, SweepSpec] = {
    reenrichment.SPEC.kind: reenrichment.SPEC,
    harmonic_status_poll.SPEC.kind: harmonic_status_poll.SPEC,
}


@activity.defn
@close_db_connections
async def sweep_select_activity(inputs: SweepInputs) -> SweepSelection:
    """Guards live here rather than in the schedule so a config flip takes effect on the next
    run without touching Temporal state.
    """
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from products.growth.backend.enrichment import gates  # noqa: PLC0415

    spec = SWEEPS[inputs.kind]
    logger = LOGGER.bind(kind=str(inputs.kind))

    if not await sync_to_async(gates.enrichment_enabled)():
        logger.info("enrichment_sweep_skipped_kill_switch")
        return spec.empty_selection
    if not gates.region_allowed():
        logger.info("enrichment_sweep_skipped_region")
        return spec.empty_selection

    return await spec.select(inputs.cap)


@activity.defn
@close_db_connections
async def sweep_process_batch_activity(inputs: SweepBatchInputs) -> dict[str, int]:
    return await SWEEPS[inputs.kind].process(inputs.items)


@activity.defn
def sweep_report_run_activity(report: SweepRunReport) -> dict[str, typing.Any]:
    event = SWEEPS[report.kind].summarize(report)

    region = get_instance_region()
    if region not in ("US", "EU"):
        LOGGER.error("enrichment_sweep_no_regional_client", kind=str(report.kind))
        return event.properties

    with ph_scoped_capture(region=region) as capture:
        capture(distinct_id=event.distinct_id, event=event.event, properties=event.properties)
    return event.properties


@workflow.defn(name="growth-enrichment-sweep")
class EnrichmentSweepWorkflow(PostHogWorkflow):
    """Sequential on purpose: the per-call rate stays trivially inside Harmonic's limit, and a
    failed batch (after its own retries) is counted and skipped, since selection re-offers its
    items on the next run if they stay eligible.
    """

    inputs_cls = SweepInputs

    @workflow.run
    async def run(self, inputs: SweepInputs) -> dict[str, typing.Any]:
        selection = await workflow.execute_activity(
            sweep_select_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        counters: dict[str, int] = {}
        failed = 0
        for batch in selection.batches:
            try:
                result = await workflow.execute_activity(
                    sweep_process_batch_activity,
                    SweepBatchInputs(kind=inputs.kind, items=batch),
                    start_to_close_timeout=dt.timedelta(seconds=selection.item_timeout_seconds),
                    retry_policy=RetryPolicy(
                        maximum_attempts=selection.item_max_attempts, initial_interval=dt.timedelta(seconds=5)
                    ),
                )
            except Exception:
                failed += len(batch)
                continue
            for key, value in result.items():
                counters[key] = counters.get(key, 0) + value

        report = SweepRunReport(
            kind=inputs.kind,
            selected=selection.selected,
            counters=counters,
            failed=failed,
            extra=selection.extra,
        )
        return await workflow.execute_activity(
            sweep_report_run_activity,
            report,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
