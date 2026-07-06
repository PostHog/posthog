"""Periodic batch refresh of persisted per-scanner volume estimates (the quota prognosis inputs)."""

import asyncio
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    ESTIMATE_REFRESH_CONCURRENCY,
    ESTIMATES_EXECUTION_TIMEOUT,
    ESTIMATES_REFRESH_INTERVAL,
    ESTIMATES_SCHEDULE_ID,
    ESTIMATES_WORKFLOW_ID,
    ESTIMATES_WORKFLOW_NAME,
    LIST_STALE_ESTIMATES_TIMEOUT,
    REFRESH_SCANNER_ESTIMATE_TIMEOUT,
)
from products.replay_vision.backend.temporal.estimates_types import (
    RefreshScannerEstimateInputs,
    RefreshScannerEstimatesInputs,
    RefreshScannerEstimatesResult,
)

if TYPE_CHECKING:
    from temporalio.client import Client

# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities import (
        list_stale_scanner_estimates_activity,
        refresh_scanner_estimate_activity,
    )


@workflow.defn(name=ESTIMATES_WORKFLOW_NAME)
class RefreshScannerEstimatesWorkflow(PostHogWorkflow):
    inputs_cls = RefreshScannerEstimatesInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: RefreshScannerEstimatesInputs) -> RefreshScannerEstimatesResult:
        stale = await workflow.execute_activity(
            list_stale_scanner_estimates_activity,
            start_to_close_timeout=LIST_STALE_ESTIMATES_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not stale:
            return RefreshScannerEstimatesResult()

        # Each refresh runs a ClickHouse count, so bound the parallelism.
        semaphore = asyncio.Semaphore(ESTIMATE_REFRESH_CONCURRENCY)

        async def refresh(entry: RefreshScannerEstimateInputs) -> None:
            async with semaphore:
                await workflow.execute_activity(
                    refresh_scanner_estimate_activity,
                    entry,
                    start_to_close_timeout=REFRESH_SCANNER_ESTIMATE_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

        # return_exceptions so one scanner's failure doesn't block the others.
        outcomes = await asyncio.gather(*(refresh(entry) for entry in stale), return_exceptions=True)
        result = RefreshScannerEstimatesResult(
            refreshed=[e.scanner_id for e, r in zip(stale, outcomes) if not isinstance(r, BaseException)],
            failed=[e.scanner_id for e, r in zip(stale, outcomes) if isinstance(r, BaseException)],
        )
        if result.failed:
            workflow.logger.warning(
                "replay_vision.estimate_refresh_partial_failure",
                extra={"failed": [str(s) for s in result.failed]},
            )
        # Total failure is likely systemic — surface it so Temporal retries.
        if not result.refreshed:
            raise ApplicationError(f"estimate refresher: all {len(stale)} refresh activities failed")
        return result


async def create_replay_vision_estimates_schedule(client: "Client") -> None:
    """Upsert the global estimate-refresher schedule. Called from worker startup."""
    # Function-local: this module contains `@workflow.defn`, and the Temporal sandbox can't
    # re-import the schedule helper's Django/temporalio.client dependencies when validating the workflow.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=ESTIMATES_SCHEDULE_ID,
        workflow_name=ESTIMATES_WORKFLOW_NAME,
        workflow_id=ESTIMATES_WORKFLOW_ID,
        inputs=RefreshScannerEstimatesInputs(),
        interval=ESTIMATES_REFRESH_INTERVAL,
        execution_timeout=ESTIMATES_EXECUTION_TIMEOUT,
    )
