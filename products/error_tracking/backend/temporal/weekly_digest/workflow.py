import asyncio
import dataclasses
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.weekly_digest.activities import (
        cleanup_digest_orgs_activity,
        get_digest_orgs_activity,
        load_page_orgs_activity,
        send_org_digest_activity,
    )
    from products.error_tracking.backend.temporal.weekly_digest.types import (
        CleanupDigestOrgsInputs,
        GetDigestOrgsInputs,
        LoadPageOrgsInputs,
        SendOrgDigestInputs,
        SendOrgDigestResult,
        WeeklyDigestInputs,
        WeeklyDigestPageInputs,
        WeeklyDigestResult,
    )

WORKFLOW_NAME = "error-tracking-weekly-digest"
PAGE_WORKFLOW_NAME = "error-tracking-weekly-digest-page"

FAILED_ORGS_ERROR_TYPE = "ErrorTrackingWeeklyDigestOrgsFailed"

DIGEST_ORGS_STORAGE_PREFIX = "error_tracking/weekly_digest"

GET_ORGS_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
GET_ORGS_TIMEOUT = timedelta(minutes=5)

LOAD_PAGE_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
LOAD_PAGE_TIMEOUT = timedelta(minutes=1)

CLEANUP_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
CLEANUP_TIMEOUT = timedelta(minutes=1)

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
    """Processes one page of orgs, read back from the list discovery stored in object
    storage. Returns counts instead of raising on org failures so the parent can
    aggregate across pages and fail the run exactly once."""

    inputs_cls = WeeklyDigestPageInputs

    @workflow.run
    async def run(self, inputs: WeeklyDigestPageInputs) -> WeeklyDigestResult:
        org_ids = await workflow.execute_activity(
            load_page_orgs_activity,
            LoadPageOrgsInputs(
                storage_key=inputs.storage_key, page_number=inputs.page_number, page_size=inputs.page_size
            ),
            start_to_close_timeout=LOAD_PAGE_TIMEOUT,
            retry_policy=LOAD_PAGE_RETRY_POLICY,
        )
        outcome = await _send_orgs(org_ids, inputs.dry_run, inputs.max_concurrent, inputs.max_attempts)
        return WeeklyDigestResult(orgs=len(org_ids), orgs_failed=outcome.orgs_failed, sent=outcome.sent)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingWeeklyDigestWorkflow(PostHogWorkflow):
    """Discovers orgs once, stores the list in object storage, and fans every page out as
    a child workflow immediately.

    Only a storage key and a count ride through workflow history, so history and payload
    sizes stay flat regardless of org count. All children start at once, so the worker
    fleet's activity-slot capacity is the intended global throttle.
    """

    inputs_cls = WeeklyDigestInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: WeeklyDigestInputs | None = None) -> WeeklyDigestResult:
        if inputs is None:
            inputs = WeeklyDigestInputs()

        # Checked before discovery so a bad value can't orphan a staged list. Zero would
        # raise ZeroDivisionError from the page arithmetic below, which Temporal retries as
        # a workflow task forever instead of failing; a negative value yields an empty page
        # range and reports a successful run that sent nothing.
        if inputs.page_size < 1:
            raise ApplicationError(f"page_size must be at least 1, got {inputs.page_size}", non_retryable=True)

        info = workflow.info()
        # run_id-scoped so a re-run of the same workflow id can never read a stale list.
        storage_key = f"{DIGEST_ORGS_STORAGE_PREFIX}/{info.workflow_id}/{info.run_id}/orgs.json"

        discovery = await workflow.execute_activity(
            get_digest_orgs_activity,
            GetDigestOrgsInputs(storage_key=storage_key, org_ids=inputs.org_ids),
            start_to_close_timeout=GET_ORGS_TIMEOUT,
            retry_policy=GET_ORGS_RETRY_POLICY,
        )

        page_count = -(-discovery.total_orgs // inputs.page_size)
        page_sizes = [
            min(inputs.page_size, discovery.total_orgs - (page_number - 1) * inputs.page_size)
            for page_number in range(1, page_count + 1)
        ]

        async def run_page(page_number: int) -> WeeklyDigestResult:
            return await workflow.execute_child_workflow(
                ErrorTrackingWeeklyDigestPageWorkflow.run,
                WeeklyDigestPageInputs(
                    storage_key=storage_key,
                    page_number=page_number,
                    page_size=inputs.page_size,
                    dry_run=inputs.dry_run,
                    max_concurrent=inputs.max_concurrent,
                    max_attempts=inputs.max_attempts,
                ),
                id=f"{info.workflow_id}-page-{page_number}",
                # Explicitly the default: terminating the parent must stop all page
                # children too, so killing the parent is a reliable stop-everything
                # switch and no abandoned child keeps sending digests.
                parent_close_policy=workflow.ParentClosePolicy.TERMINATE,
            )

        results = await asyncio.gather(
            *(run_page(page_number) for page_number in range(1, page_count + 1)), return_exceptions=True
        )

        if discovery.total_orgs:
            # Best-effort: a leftover object costs pennies and the bucket can carry a
            # lifecycle rule; failing the whole run over cleanup would be backwards.
            try:
                await workflow.execute_activity(
                    cleanup_digest_orgs_activity,
                    CleanupDigestOrgsInputs(storage_key=storage_key),
                    start_to_close_timeout=CLEANUP_TIMEOUT,
                    retry_policy=CLEANUP_RETRY_POLICY,
                )
            except Exception as error:
                workflow.logger.warning(
                    "Error Tracking weekly digest org list cleanup failed",
                    extra={"storage_key": storage_key, "error": str(error)},
                )

        orgs = 0
        orgs_failed = 0
        sent = 0
        for page_size, result in zip(page_sizes, results):
            orgs += page_size
            # Same as _send_orgs: a captured CancelledError is the run being cancelled,
            # not a failed page.
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                # The child only propagates unexpected failures (per-org errors are counted
                # inside it), so attribute the whole page.
                orgs_failed += page_size
                workflow.logger.error(
                    "Error Tracking weekly digest page failed",
                    extra={"page_size": page_size, "error": str(result)},
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
