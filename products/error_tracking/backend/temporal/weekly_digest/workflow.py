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
        WeeklyDigestPageInputs,
        WeeklyDigestResult,
    )

WORKFLOW_NAME = "error-tracking-weekly-digest"
PAGE_WORKFLOW_NAME = "error-tracking-weekly-digest-page"

FAILED_ORGS_ERROR_TYPE = "ErrorTrackingWeeklyDigestOrgsFailed"

GET_ORGS_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
GET_ORGS_TIMEOUT = timedelta(minutes=5)

SEND_ORG_START_TO_CLOSE_TIMEOUT = timedelta(minutes=30)
SEND_ORG_HEARTBEAT_TIMEOUT = timedelta(minutes=5)
SEND_ORG_INITIAL_RETRY_INTERVAL = timedelta(seconds=1)
SEND_ORG_MAXIMUM_RETRY_INTERVAL = timedelta(seconds=30)


def _sent_from_error(error: BaseException) -> int:
    """Digests a failed org still sent, as carried in the activity's ApplicationError details.

    Returns 0 for failures that carry no count, such as a timeout or a crash outside the activity's
    own error path.
    """
    details = getattr(getattr(error, "cause", None), "details", None) or ()
    return details[0] if details and isinstance(details[0], int) else 0


@dataclasses.dataclass(frozen=True, kw_only=True)
class _PageOutcome:
    sent: int
    orgs_failed: int


async def _send_orgs(org_ids: list[str], dry_run: bool, max_concurrent: int, max_attempts: int) -> _PageOutcome:
    """Run the per-org digest activities for one page, ``max_concurrent`` at a time.

    Must be called from within a workflow.
    """
    # Keep up to max_concurrent per-org activities in flight at all times: the semaphore
    # releases the moment one finishes, so the next org starts immediately rather than
    # waiting for a whole wave to drain.
    semaphore = asyncio.Semaphore(max_concurrent)

    async def send_org(org_id: str) -> SendOrgDigestResult:
        async with semaphore:
            return await workflow.execute_activity(
                send_org_digest_activity,
                SendOrgDigestInputs(org_id=org_id, dry_run=dry_run, max_attempts=max_attempts),
                start_to_close_timeout=SEND_ORG_START_TO_CLOSE_TIMEOUT,
                heartbeat_timeout=SEND_ORG_HEARTBEAT_TIMEOUT,
                retry_policy=common.RetryPolicy(
                    # Must match SendOrgDigestInputs.max_attempts — final-attempt detection
                    # inside the activity depends on the two agreeing.
                    maximum_attempts=max_attempts,
                    initial_interval=SEND_ORG_INITIAL_RETRY_INTERVAL,
                    backoff_coefficient=2.0,
                    maximum_interval=SEND_ORG_MAXIMUM_RETRY_INTERVAL,
                ),
            )

    results = await asyncio.gather(*(send_org(org_id) for org_id in org_ids), return_exceptions=True)

    sent = 0
    orgs_failed = 0
    for org_id, result in zip(org_ids, results):
        # Workflow cancellation lands here as a captured CancelledError; counting it as an
        # org failure would keep the run going instead of honoring the cancel.
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            orgs_failed += 1
            sent += _sent_from_error(result)
            workflow.logger.error(
                "Error Tracking weekly digest org failed after retries",
                extra={"org_id": org_id, "error": str(result)},
            )
            continue
        sent += result.sent
    return _PageOutcome(sent=sent, orgs_failed=orgs_failed)


@workflow.defn(name=PAGE_WORKFLOW_NAME)
class ErrorTrackingWeeklyDigestPageWorkflow(PostHogWorkflow):
    """Processes one page of orgs. Returns counts instead of raising on org failures so the
    parent can aggregate across pages and fail the run exactly once."""

    inputs_cls = WeeklyDigestPageInputs

    @workflow.run
    async def run(self, inputs: WeeklyDigestPageInputs) -> WeeklyDigestResult:
        outcome = await _send_orgs(inputs.org_ids, inputs.dry_run, inputs.max_concurrent, inputs.max_attempts)
        return WeeklyDigestResult(orgs=len(inputs.org_ids), orgs_failed=outcome.orgs_failed, sent=outcome.sent)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingWeeklyDigestWorkflow(PostHogWorkflow):
    """Fans pages of orgs out as child workflows, ``max_concurrent_pages`` at a time.

    Overlapping pages keeps activity slots busy while a page drains its slowest orgs —
    with sequential pages, each page's tail (one slow org retrying) idles the whole
    fleet until the next page starts.
    """

    inputs_cls = WeeklyDigestInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: WeeklyDigestInputs | None = None) -> WeeklyDigestResult:
        if inputs is None:
            inputs = WeeklyDigestInputs()

        window = asyncio.Semaphore(inputs.max_concurrent_pages)

        async def run_page(org_ids: list[str], page_number: int) -> WeeklyDigestResult:
            async with window:
                return await workflow.execute_child_workflow(
                    ErrorTrackingWeeklyDigestPageWorkflow.run,
                    WeeklyDigestPageInputs(
                        org_ids=org_ids,
                        dry_run=inputs.dry_run,
                        max_concurrent=inputs.max_concurrent,
                        max_attempts=inputs.max_attempts,
                    ),
                    id=f"{workflow.info().workflow_id}-page-{page_number}",
                    # Explicitly the default: terminating the parent must stop all page
                    # children too, so killing the parent is a reliable stop-everything
                    # switch and no abandoned child keeps sending digests.
                    parent_close_policy=workflow.ParentClosePolicy.TERMINATE,
                )

        cursor: str | None = None
        pages: list[list[str]] = []
        page_tasks: list[asyncio.Task[WeeklyDigestResult]] = []
        while True:
            page = await workflow.execute_activity(
                get_digest_orgs_activity,
                GetDigestOrgsInputs(org_ids=inputs.org_ids, after=cursor, limit=inputs.page_size),
                start_to_close_timeout=GET_ORGS_TIMEOUT,
                retry_policy=GET_ORGS_RETRY_POLICY,
            )
            if not page:
                break
            pages.append(page)
            page_tasks.append(asyncio.create_task(run_page(page, page_number=len(pages))))
            if len(page) < inputs.page_size:
                break
            cursor = page[-1]

        results = await asyncio.gather(*page_tasks, return_exceptions=True)

        orgs = 0
        orgs_failed = 0
        sent = 0
        for page, result in zip(pages, results):
            orgs += len(page)
            # Same as _send_orgs: a captured CancelledError is the run being cancelled,
            # not a failed page.
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                # The child only propagates unexpected failures (per-org errors are counted
                # inside it), so attribute the whole page.
                orgs_failed += len(page)
                workflow.logger.error(
                    "Error Tracking weekly digest page failed",
                    extra={"page_size": len(page), "error": str(result)},
                )
                continue
            orgs_failed += result.orgs_failed
            sent += result.sent

        if not orgs:
            workflow.logger.info("No orgs for Error Tracking weekly digest")

        workflow.logger.info(
            "Error Tracking weekly digest run complete",
            extra={"orgs": orgs, "orgs_failed": orgs_failed, "sent": sent, "dry_run": inputs.dry_run},
        )

        if orgs_failed:
            raise ApplicationError(
                f"Error Tracking weekly digest failed for {orgs_failed}/{orgs} orgs "
                f"({sent} digests sent, including partial sends from the failed orgs)",
                type=FAILED_ORGS_ERROR_TYPE,
                non_retryable=True,
            )

        return WeeklyDigestResult(orgs=orgs, orgs_failed=orgs_failed, sent=sent)
