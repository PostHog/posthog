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
from products.signals.backend.temporal.types import SignalReportDeletionWorkflowInputs

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Soft-delete ALL signal reports for a given team using the Temporal deletion workflow."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, required=True, help="The ID of the team whose reports should be deleted."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="List reports that would be deleted without actually deleting them.",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
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

        logger.info("Found %d report(s) for team %d (%s).", report_count, team_id, team.name)

        if dry_run:
            for report in reports:
                logger.info("[DRY RUN] Would delete report %s — %s (status=%s)", report.id, report.title, report.status)
            logger.info("Dry run complete. %d report(s) would be deleted.", report_count)
            return

        client = sync_connect()
        started = 0
        skipped = 0
        failed = 0

        for report in reports:
            report_id = str(report.id)
            workflow_id = SignalReportDeletionWorkflow.workflow_id_for(team_id, report_id)

            try:
                async_to_sync(client.start_workflow)(  # type: ignore
                    "signal-report-deletion",  # type: ignore
                    SignalReportDeletionWorkflowInputs(team_id=team_id, report_id=report_id),  # type: ignore
                    id=workflow_id,
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    execution_timeout=timedelta(minutes=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                started += 1
                logger.info("Started deletion workflow for report %s — %s", report_id, report.title)
            except WorkflowAlreadyStartedError:
                skipped += 1
                logger.warning("Deletion already running for report %s, skipping.", report_id)
            except Exception:
                failed += 1
                logger.exception("Failed to start deletion workflow for report %s", report_id)

        logger.info(
            "Done. Started: %d, Already running: %d, Failed: %d (total: %d)", started, skipped, failed, report_count
        )
