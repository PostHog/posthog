import json
import asyncio
import dataclasses
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.web_analytics.backend.temporal.digest_common import ACTIVITY_RETRY_POLICY
    from products.web_analytics.backend.temporal.weekly_digest.activities import (
        get_org_batch_page,
        push_wa_digest_metrics_activity,
        run_wa_digest_batch,
        send_test_wa_digest,
    )
    from products.web_analytics.backend.temporal.weekly_digest.types import (
        WA_DIGEST_THRESHOLD_EXCEEDED_TYPE,
        DigestBatchInput,
        DigestBatchResult,
        OrgBatchPageInput,
        SendTestDigestInput,
        WAWeeklyDigestInput,
    )


@workflow.defn(name="wa-weekly-digest")
class WAWeeklyDigestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WAWeeklyDigestInput:
        if inputs:
            data = json.loads(inputs[0])
            return WAWeeklyDigestInput(
                **{f.name: data[f.name] for f in dataclasses.fields(WAWeeklyDigestInput) if f.name in data}
            )
        return WAWeeklyDigestInput()

    @workflow.run
    async def run(self, input: WAWeeklyDigestInput | None = None) -> dict:
        if input is None:
            input = WAWeeklyDigestInput()

        totals = DigestBatchResult()
        failed_batches = 0
        batch_count = 0
        cursor: str | None = None
        semaphore = asyncio.Semaphore(input.max_concurrent)

        async def _run_batch(batch: list[str]) -> DigestBatchResult:
            async with semaphore:
                return await workflow.execute_activity(
                    run_wa_digest_batch,
                    DigestBatchInput(org_ids=batch, dry_run=input.dry_run),
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
                    "Fanning out WA digest page",
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
                        workflow.logger.error("WA digest batch failed: %s", str(r))
                    else:
                        totals += r

            if page.cursor is None:
                break
            cursor = page.cursor

        if batch_count == 0:
            workflow.logger.info("No org batches for WA weekly digest")

        threshold_exceeded = totals.batch_size > 0 and totals.failure_rate > input.failure_threshold

        await workflow.execute_activity(
            push_wa_digest_metrics_activity,
            args=[dataclasses.asdict(totals), not threshold_exceeded],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        if threshold_exceeded:
            raise ApplicationError(
                f"WA weekly digest: {totals.orgs_failed:,}/{totals.batch_size:,} orgs failed "
                f"({totals.failure_rate:.1%}), exceeds threshold {input.failure_threshold:.1%} "
                f"(skipped={totals.orgs_skipped:,} not counted toward failure rate)",
                type=WA_DIGEST_THRESHOLD_EXCEEDED_TYPE,
                non_retryable=True,
            )

        return {
            "orgs": totals.batch_size,
            "batches": batch_count,
            "failed_batches": failed_batches,
            "emails_sent": totals.emails_sent,
            "emails_failed": totals.emails_failed,
            "cumulative_duration_seconds": totals.total_duration,
        }


@workflow.defn(name="wa-weekly-digest-test")
class WAWeeklyDigestTestWorkflow(PostHogWorkflow):
    """Send a test digest, bypassing notification settings and feature flags. See `SendTestDigestInput`."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SendTestDigestInput:
        """Parse inputs from the management command CLI.

        Usage:
          manage.py start_temporal_workflow wa-weekly-digest-test '{"email": "you@example.com"}'
          manage.py start_temporal_workflow wa-weekly-digest-test '{"email": "you@example.com", "team_id": 1}'
        """
        data = json.loads(inputs[0])
        return SendTestDigestInput(
            email=data["email"],
            team_id=data.get("team_id"),
        )

    @workflow.run
    async def run(self, input: SendTestDigestInput) -> None:
        await workflow.execute_activity(
            send_test_wa_digest,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
