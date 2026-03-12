import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.temporal.common.client import sync_connect

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


class Command(BaseCommand):
    help = "Delete or re-ingest ALL signal reports for a given team using the appropriate Temporal workflow. Defaults to re-ingestion."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, required=True, help="The ID of the team whose reports should be processed."
        )
        parser.add_argument(
            "--action",
            choices=[ACTION_DELETE, ACTION_REINGEST],
            default=ACTION_REINGEST,
            help="Whether to delete or re-ingest reports. Defaults to reingest.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="List reports that would be affected without actually starting any workflows.",
        )

    def handle(self, *args, **options):
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

        client = sync_connect()
        started = 0
        skipped = 0
        failed = 0

        for report in reports:
            report_id = str(report.id)

            workflow_inputs: SignalReportDeletionWorkflowInputs | SignalReportReingestionWorkflowInputs
            if action == ACTION_DELETE:
                workflow_name = "signal-report-deletion"
                workflow_id = SignalReportDeletionWorkflow.workflow_id_for(team_id, report_id)
                workflow_inputs = SignalReportDeletionWorkflowInputs(team_id=team_id, report_id=report_id)
            else:
                workflow_name = "signal-report-reingestion"
                workflow_id = SignalReportReingestionWorkflow.workflow_id_for(team_id, report_id)
                workflow_inputs = SignalReportReingestionWorkflowInputs(team_id=team_id, report_id=report_id)

            try:
                async_to_sync(client.start_workflow)(  # type: ignore
                    workflow_name,  # type: ignore
                    workflow_inputs,  # type: ignore
                    id=workflow_id,
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    execution_timeout=timedelta(minutes=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                started += 1
                logger.info("Started %s workflow for report %s — %s", action, report_id, report.title)
            except WorkflowAlreadyStartedError:
                skipped += 1
                logger.warning("Workflow already running for report %s, skipping.", report_id)
            except Exception:
                failed += 1
                logger.exception("Failed to start %s workflow for report %s", action, report_id)

        logger.info(
            "Done. Started: %d, Already running: %d, Failed: %d (total: %d)", started, skipped, failed, report_count
        )
