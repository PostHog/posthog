import json
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from products.reaper_hog.backend.temporal.activities import (
    harvest_activity,
    scan_activity,
    sync_activity,
    verify_activity,
)
from products.reaper_hog.backend.temporal.types import REAP_SCOPE_WORKFLOW, ReapScopeInputs, ScanActivityResult

_SCAN_TIMEOUT = timedelta(minutes=30)
_VERIFY_TIMEOUT = timedelta(hours=4)
_QUICK_TIMEOUT = timedelta(minutes=10)
_HEARTBEAT = timedelta(minutes=5)
_RETRY = RetryPolicy(maximum_attempts=2)


@temporalio.workflow.defn(name=REAP_SCOPE_WORKFLOW)
class ReapScopeWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ReapScopeInputs:
        return ReapScopeInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ReapScopeInputs) -> str:
        workflow.logger.info(f"ReaperHog: scanning {inputs.repository} scope {inputs.scope}")
        scan: ScanActivityResult = await workflow.execute_activity(
            scan_activity,
            inputs,
            start_to_close_timeout=_SCAN_TIMEOUT,
            heartbeat_timeout=_HEARTBEAT,
            retry_policy=_RETRY,
        )
        workflow.logger.info(
            f"ReaperHog: {scan.cluster_count} clusters ({scan.strong_count} strong) at {scan.head_sha[:12]}"
        )
        if inputs.verify:
            verified = await workflow.execute_activity(
                verify_activity,
                inputs,
                start_to_close_timeout=_VERIFY_TIMEOUT,
                heartbeat_timeout=_HEARTBEAT,
                retry_policy=_RETRY,
            )
            workflow.logger.info(f"ReaperHog: verified {verified.verified}, {verified.dead} dead")
        synced = await workflow.execute_activity(
            sync_activity, inputs, start_to_close_timeout=_QUICK_TIMEOUT, retry_policy=_RETRY
        )
        workflow.logger.info(f"ReaperHog: {synced.reaped} opened, {synced.buried} merged, {synced.declined} closed")
        if inputs.harvest:
            harvested = await workflow.execute_activity(
                harvest_activity, inputs, start_to_close_timeout=_QUICK_TIMEOUT, retry_policy=_RETRY
            )
            workflow.logger.info(f"ReaperHog: dispatched {harvested.dispatched} harvest task(s)")
        return scan.inventory_id
