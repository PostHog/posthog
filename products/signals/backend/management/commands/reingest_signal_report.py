from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.reingestion import SignalReportReingestionWorkflow
from products.signals.backend.temporal.types import SignalReportReingestionWorkflowInputs


async def _start_report_reingestion_workflow(team_id: int, report_id: str) -> None:
    client = await async_connect()
    await client.start_workflow(
        SignalReportReingestionWorkflow.run,
        SignalReportReingestionWorkflowInputs(team_id=team_id, report_id=report_id),
        id=SignalReportReingestionWorkflow.workflow_id_for(team_id, report_id),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        execution_timeout=timedelta(minutes=30),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


class Command(BaseCommand):
    help = (
        "Re-ingest specific signal reports: delete each report and re-emit its signals "
        "through the active pipeline so they are regrouped and re-researched from scratch."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("report_ids", nargs="+", help="One or more SignalReport UUIDs to reingest.")
        parser.add_argument("--team-id", type=int, required=True, help="The ID of the team the reports belong to.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        report_ids: list[str] = options["report_ids"]

        try:
            Team.objects.get(id=team_id)
        except Team.DoesNotExist as err:
            raise CommandError(f"Team {team_id} not found") from err

        for report_id in report_ids:
            try:
                report = SignalReport.objects.get(id=report_id, team_id=team_id)
            except (SignalReport.DoesNotExist, ValidationError) as err:
                raise CommandError(f"Report {report_id} not found in team {team_id}") from err

            workflow_id = SignalReportReingestionWorkflow.workflow_id_for(team_id, str(report.id))

            try:
                async_to_sync(_start_report_reingestion_workflow)(team_id, str(report.id))
            except WorkflowAlreadyStartedError:
                self.stdout.write(
                    self.style.WARNING(
                        f"Reingestion workflow already running for report {report.id} [workflow_id={workflow_id}]"
                    )
                )
                continue

            self.stdout.write(
                self.style.SUCCESS(
                    f"Started reingestion for report {report.id} (status={report.status}, "
                    f"signals={report.signal_count}) [workflow_id={workflow_id}]"
                )
            )
