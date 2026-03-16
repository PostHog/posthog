import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from asgiref.sync import async_to_sync
from temporalio.client import WorkflowHandle
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.deletion import SignalReportDeletionWorkflow
from products.signals.backend.temporal.reingestion import SignalReportReingestionWorkflow
from products.signals.backend.temporal.types import (
    SignalReportDeletionWorkflowInputs,
    SignalReportReingestionWorkflowInputs,
)

logger = logging.getLogger(__name__)

ACTION_DELETE = "delete"
ACTION_REINGEST = "reingest"
DEFAULT_BATCH_SIZE = 50

WORKFLOW_CONFIG: dict[str, dict] = {
    ACTION_DELETE: {
        "workflow_name": "signal-report-deletion",
        "workflow_id_fn": SignalReportDeletionWorkflow.workflow_id_for,
        "inputs_cls": SignalReportDeletionWorkflowInputs,
    },
    ACTION_REINGEST: {
        "workflow_name": "signal-report-reingestion",
        "workflow_id_fn": SignalReportReingestionWorkflow.workflow_id_for,
        "inputs_cls": SignalReportReingestionWorkflowInputs,
    },
}


async def _run_workflows_batched(
    team_id: int,
    reports: list[tuple[str, str]],
    action: str,
    batch_size: int,
) -> tuple[int, int, int, int]:
    """Start workflows in batches, waiting for each batch to complete before starting the next."""
    client = await async_connect()
    config = WORKFLOW_CONFIG[action]
    # Track the progress
    started = 0
    skipped = 0
    start_failed = 0
    execution_failed = 0
    total = len(reports)
    total_batches = (total + batch_size - 1) // batch_size
    # Split the jobs into batches and process
    for batch_idx in range(0, total, batch_size):
        batch = reports[batch_idx : batch_idx + batch_size]
        batch_num = batch_idx // batch_size + 1
        logger.info("Starting batch %d/%d (%d reports)", batch_num, total_batches, len(batch))
        handles: list[tuple[str, str, WorkflowHandle]] = []
        for report_id, title in batch:
            workflow_id = config["workflow_id_fn"](team_id, report_id)
            workflow_inputs = config["inputs_cls"](team_id=team_id, report_id=report_id)
            try:
                handle = await client.start_workflow(
                    config["workflow_name"],
                    workflow_inputs,
                    id=workflow_id,
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    execution_timeout=timedelta(minutes=90),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                handles.append((report_id, title, handle))
                started += 1
                logger.info("Started %s workflow for report %s — %s", action, report_id, title)
            except WorkflowAlreadyStartedError:
                skipped += 1
                logger.warning("Workflow already running for report %s, skipping.", report_id)
            except Exception:
                start_failed += 1
                logger.exception("Failed to start %s workflow for report %s", action, report_id)
        # Wait for all workflows in this batch to complete before starting the next
        for report_id, title, handle in handles:
            try:
                await handle.result()
                logger.info("Completed %s for report %s — %s", action, report_id, title)
            except Exception:
                execution_failed += 1
                logger.exception("Workflow failed for report %s — %s", report_id, title)
        logger.info("Batch %d/%d complete", batch_num, total_batches)
    return started, skipped, start_failed, execution_failed


class Command(BaseCommand):
    help = "Delete or re-ingest ALL signal reports for a given team using the appropriate Temporal workflow. Defaults to deletion."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, required=True, help="The ID of the team whose reports should be processed."
        )
        parser.add_argument(
            "--action",
            choices=[ACTION_DELETE, ACTION_REINGEST],
            default=ACTION_DELETE,
            help="Whether to delete or re-ingest reports. Defaults to delete.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="List reports that would be affected without actually starting any workflows.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of workflows to run concurrently per batch. Defaults to {DEFAULT_BATCH_SIZE}.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1")

        team_id = options["team_id"]
        action = options["action"]
        dry_run = options["dry_run"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.exception("Team %d does not exist.", team_id)
            return

        # Fetch all non-deleted reports for the team
        reports = SignalReport.objects.filter(team=team).exclude(status=SignalReport.Status.DELETED)
        report_count = reports.count()

        if report_count == 0:
            logger.info("No active reports found for team %d. Nothing to do.", team_id)
            return

        logger.info("Found %d report(s) for team %d (%s). Action: %s", report_count, team_id, team.name, action)

        if dry_run:
            for report in reports:
                logger.info(
                    "[DRY RUN] Would %s report %s — %s (status=%s)", action, report.id, report.title, report.status
                )
            logger.info("Dry run complete. %d report(s) would be affected.", report_count)
            return

        report_data = [(str(id), title or "") for id, title in reports.values_list("id", "title")]
        started, skipped, start_failed, execution_failed = async_to_sync(_run_workflows_batched)(
            team_id, report_data, action, batch_size
        )
        total_failed = start_failed + execution_failed
        completed = started - execution_failed
        logger.info(
            "Done. Started: %d, Completed: %d, Already running: %d, Start failed: %d, Execution failed: %d (total: %d)",
            started,
            completed,
            skipped,
            start_failed,
            execution_failed,
            report_count,
        )
        if total_failed > 0 and completed == 0 and skipped == 0:
            raise CommandError(f"All {total_failed} workflow(s) failed out of {report_count}")
        elif total_failed > 0:
            logger.warning("%d workflow(s) failed out of %d", total_failed, report_count)
