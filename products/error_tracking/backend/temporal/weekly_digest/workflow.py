import asyncio
import dataclasses
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.weekly_digest.activities import (
        get_digest_orgs_activity,
        send_org_digest_activity,
    )
    from products.error_tracking.backend.temporal.weekly_digest.types import (
        GetDigestOrgsInputs,
        SendOrgDigestInputs,
        SendOrgDigestResult,
        WeeklyDigestInputs,
        WeeklyDigestResult,
    )

WORKFLOW_NAME = "error-tracking-weekly-digest"

FAILED_ORGS_ERROR_TYPE = "ErrorTrackingWeeklyDigestOrgsFailed"

GET_ORGS_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
GET_ORGS_TIMEOUT = timedelta(minutes=5)

SEND_ORG_START_TO_CLOSE_TIMEOUT = timedelta(minutes=30)
SEND_ORG_HEARTBEAT_TIMEOUT = timedelta(minutes=5)
SEND_ORG_INITIAL_RETRY_INTERVAL = timedelta(seconds=30)
SEND_ORG_MAXIMUM_RETRY_INTERVAL = timedelta(minutes=5)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingWeeklyDigestWorkflow(PostHogWorkflow):
    inputs_cls = WeeklyDigestInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: WeeklyDigestInputs | None = None) -> WeeklyDigestResult:
        if inputs is None:
            inputs = WeeklyDigestInputs()

        # One keyset page per execution: only the ~40-byte cursor rides through
        # continue_as_new, so neither history nor payload size grows with org count.
        page = await workflow.execute_activity(
            get_digest_orgs_activity,
            GetDigestOrgsInputs(org_ids=inputs.org_ids, after=inputs.cursor, limit=inputs.page_size),
            start_to_close_timeout=GET_ORGS_TIMEOUT,
            retry_policy=GET_ORGS_RETRY_POLICY,
        )

        # Keep up to max_concurrent per-org activities in flight at all times: the semaphore
        # releases the moment one finishes, so the next org starts immediately rather than
        # waiting for a whole wave to drain.
        semaphore = asyncio.Semaphore(inputs.max_concurrent)

        async def send_org(org_id: str) -> SendOrgDigestResult:
            async with semaphore:
                return await workflow.execute_activity(
                    send_org_digest_activity,
                    SendOrgDigestInputs(org_id=org_id, dry_run=inputs.dry_run, max_attempts=inputs.max_attempts),
                    start_to_close_timeout=SEND_ORG_START_TO_CLOSE_TIMEOUT,
                    heartbeat_timeout=SEND_ORG_HEARTBEAT_TIMEOUT,
                    retry_policy=common.RetryPolicy(
                        # Must match SendOrgDigestInputs.max_attempts — final-attempt detection
                        # inside the activity depends on the two agreeing.
                        maximum_attempts=inputs.max_attempts,
                        initial_interval=SEND_ORG_INITIAL_RETRY_INTERVAL,
                        backoff_coefficient=2.0,
                        maximum_interval=SEND_ORG_MAXIMUM_RETRY_INTERVAL,
                    ),
                )

        results = await asyncio.gather(*(send_org(org_id) for org_id in page), return_exceptions=True)

        sent = inputs.carried_sent
        orgs_failed = inputs.carried_orgs_failed
        for org_id, result in zip(page, results):
            if isinstance(result, BaseException):
                orgs_failed += 1
                workflow.logger.error(
                    "Error Tracking weekly digest org failed after retries",
                    extra={"org_id": org_id, "error": str(result)},
                )
                continue
            sent += result.sent

        orgs = inputs.carried_orgs + len(page)

        # A full page may hide more orgs behind it; only a short page proves the set is
        # drained. An exact-multiple total costs one extra execution that gets an empty
        # page and finishes with the carried totals.
        if page and len(page) == inputs.page_size:
            workflow.logger.info(
                "Error Tracking weekly digest page complete, continuing as new",
                extra={"orgs_so_far": orgs, "cursor": page[-1], "orgs_failed": orgs_failed, "sent": sent},
            )
            workflow.continue_as_new(
                dataclasses.replace(
                    inputs,
                    cursor=page[-1],
                    carried_orgs=orgs,
                    carried_orgs_failed=orgs_failed,
                    carried_sent=sent,
                )
            )

        if not orgs:
            workflow.logger.info("No orgs for Error Tracking weekly digest")

        workflow.logger.info(
            "Error Tracking weekly digest run complete",
            extra={"orgs": orgs, "orgs_failed": orgs_failed, "sent": sent, "dry_run": inputs.dry_run},
        )

        if orgs_failed:
            raise ApplicationError(
                f"Error Tracking weekly digest failed for {orgs_failed}/{orgs} orgs "
                f"({sent} digests sent to recipients in healthy orgs)",
                type=FAILED_ORGS_ERROR_TYPE,
                non_retryable=True,
            )

        return WeeklyDigestResult(orgs=orgs, orgs_failed=orgs_failed, sent=sent)
