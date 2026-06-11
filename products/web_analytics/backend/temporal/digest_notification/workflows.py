import json
import asyncio
import dataclasses
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.web_analytics.backend.temporal.digest_common import ACTIVITY_RETRY_POLICY
    from products.web_analytics.backend.temporal.digest_notification.activities import (
        get_org_batch_page,
        run_wa_digest_notification_batch,
        send_test_wa_digest_notification,
    )
    from products.web_analytics.backend.temporal.digest_notification.types import (
        WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE,
        DigestBatchInput,
        DigestBatchResult,
        OrgBatchPageInput,
        SendTestDigestNotificationInput,
        WADigestNotificationInput,
    )


@workflow.defn(name="wa-digest-notification")
class WADigestNotificationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WADigestNotificationInput:
        if inputs:
            data = json.loads(inputs[0])
            return WADigestNotificationInput(
                **{f.name: data[f.name] for f in dataclasses.fields(WADigestNotificationInput) if f.name in data}
            )
        return WADigestNotificationInput()

    @workflow.run
    async def run(self, input: WADigestNotificationInput | None = None) -> dict:
        if input is None:
            input = WADigestNotificationInput()

        totals = DigestBatchResult()
        failed_batches = 0
        batch_count = 0
        cursor: str | None = None
        semaphore = asyncio.Semaphore(input.max_concurrent)

        async def _run_batch(batch: list[str]) -> DigestBatchResult:
            async with semaphore:
                return await workflow.execute_activity(
                    run_wa_digest_notification_batch,
                    DigestBatchInput(org_ids=batch, dry_run=input.dry_run, flag_key=input.flag_key),
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )

        while True:
            page = await workflow.execute_activity(
                get_org_batch_page,
                OrgBatchPageInput(workflow_input=input, cursor=cursor),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

            if page.batches:
                workflow.logger.info(
                    "Fanning out WA digest notification page",
                    batches=len(page.batches),
                    orgs=page.org_count,
                    cursor=cursor,
                    next_cursor=page.cursor,
                )

                batch_count += len(page.batches)
                results = await asyncio.gather(
                    *[_run_batch(b) for b in page.batches],
                    return_exceptions=True,
                )

                for batch, r in zip(page.batches, results):
                    if isinstance(r, BaseException):
                        failed_batches += 1
                        totals += DigestBatchResult(batch_size=len(batch), orgs_failed=len(batch))
                        workflow.logger.error("WA digest notification batch failed: %s", str(r))
                    else:
                        totals += r

            if page.cursor is None:
                break
            cursor = page.cursor

        if batch_count == 0:
            workflow.logger.info("No org batches for WA digest notification")

        threshold_exceeded = totals.batch_size > 0 and totals.failure_rate > input.failure_threshold

        if threshold_exceeded:
            raise ApplicationError(
                f"WA digest notification: {totals.orgs_failed:,}/{totals.batch_size:,} orgs failed "
                f"({totals.failure_rate:.1%}), exceeds threshold {input.failure_threshold:.1%} "
                f"(skipped={totals.orgs_skipped:,} not counted toward failure rate)",
                type=WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE,
                non_retryable=True,
            )

        return {
            "orgs": totals.batch_size,
            "batches": batch_count,
            "failed_batches": failed_batches,
            "notifications_sent": totals.notifications_sent,
            "control_exposed": totals.control_exposed,
            "failed": totals.failed,
            "cumulative_duration_seconds": totals.total_duration,
        }


@workflow.defn(name="wa-digest-notification-test")
class WADigestNotificationTestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SendTestDigestNotificationInput:
        data = json.loads(inputs[0])
        return SendTestDigestNotificationInput(
            email=data["email"],
            team_id=data.get("team_id"),
        )

    @workflow.run
    async def run(self, input: SendTestDigestNotificationInput) -> None:
        await workflow.execute_activity(
            send_test_wa_digest_notification,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
