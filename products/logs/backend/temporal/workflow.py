"""Temporal workflow for logs alert checking — two-phase fan-out."""

import asyncio
from itertools import batched

import temporalio
from temporalio import workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

# Activities (and their dataclass payloads) live behind Django imports — gettext
# in particular is blocked by Temporal's workflow sandbox. Mark these as
# pass-through; we never call the activity functions from workflow code, only
# pass them as references to `execute_activity`.
with workflow.unsafe.imports_passed_through():
    from products.logs.backend.temporal.activities import (
        CheckAlertsInput,
        CheckAlertsOutput,
        DiscoverCohortsInput,
        DiscoverCohortsOutput,
        EvaluateCohortBatchInput,
        EvaluateCohortBatchOutput,
        discover_cohorts_activity,
        evaluate_cohort_batch_activity,
    )

from products.logs.backend.temporal.constants import ACTIVITY_RETRY_POLICY, ACTIVITY_TIMEOUT, WORKFLOW_NAME


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class LogsAlertCheckWorkflow(PostHogWorkflow):
    """Two-phase fan-out: discover cohort manifests, then evaluate batches in parallel.

    Workflows can't do I/O; the discovery activity owns the Postgres query and
    returns serialisable manifests recorded in workflow history. The workflow
    then deterministically chunks the manifests into batches and dispatches one
    activity per batch via `asyncio.gather` — Temporal spreads them across
    available worker pods.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckAlertsInput:
        return CheckAlertsInput()

    @temporalio.workflow.run
    async def run(self, input: CheckAlertsInput) -> CheckAlertsOutput:
        discovery: DiscoverCohortsOutput = await workflow.execute_activity(
            discover_cohorts_activity,
            DiscoverCohortsInput(),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        if not discovery.manifests:
            return CheckAlertsOutput(alerts_checked=0, alerts_fired=0, alerts_resolved=0, alerts_errored=0)

        # Use the batch size recorded by discovery rather than reading env here —
        # module-level env reads are non-deterministic across workflow replay.
        batches = [
            EvaluateCohortBatchInput(manifests=list(chunk))
            for chunk in batched(discovery.manifests, discovery.batch_size)
        ]

        # `return_exceptions=True` isolates per-batch retry-exhaustion: one
        # batch's `ActivityError` doesn't abort the cycle.
        results: list[EvaluateCohortBatchOutput | BaseException] = await asyncio.gather(
            *(
                workflow.execute_activity(
                    evaluate_cohort_batch_activity,
                    batch,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                for batch in batches
            ),
            return_exceptions=True,
        )

        alerts_checked = 0
        alerts_fired = 0
        alerts_resolved = 0
        alerts_errored = 0
        for batch, result in zip(batches, results):
            if isinstance(result, ActivityError):
                # Batch's retries exhausted — count its alerts as errored, keep going.
                workflow.logger.warning(
                    "Cohort batch activity failed; counting batch alerts as errored",
                    cohort_count=len(batch.manifests),
                )
                alerts_errored += sum(len(m.alert_ids) for m in batch.manifests)
            elif isinstance(result, BaseException):
                # Unexpected exception type — re-raise so the workflow fails loudly
                # rather than silently masking a bug.
                raise result
            else:
                alerts_checked += result.alerts_checked
                alerts_fired += result.alerts_fired
                alerts_resolved += result.alerts_resolved
                alerts_errored += result.alerts_errored

        return CheckAlertsOutput(
            alerts_checked=alerts_checked,
            alerts_fired=alerts_fired,
            alerts_resolved=alerts_resolved,
            alerts_errored=alerts_errored,
        )
