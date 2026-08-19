from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalReportCanvas
from products.signals.backend.temporal.report_canvas import SignalReportCanvasWorkflow, start_report_canvas_workflow


class Command(BaseCommand):
    help = "Preview or start report canvas generation for an explicit set of Signal reports."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("report_ids", nargs="+", help="One or more SignalReport UUIDs to backfill.")
        parser.add_argument("--team-id", type=int, required=True, help="The ID of the team the reports belong to.")
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Start generation. Without this option, the command only previews the selected reports.",
        )
        parser.add_argument(
            "--notify-reviewers",
            action="store_true",
            help="Notify suggested reviewers after successful generation. Notifications are off by default.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        report_ids: list[str] = options["report_ids"]
        execute: bool = options["execute"]
        notify_reviewers: bool = options["notify_reviewers"]

        if notify_reviewers and not execute:
            raise CommandError("--notify-reviewers requires --execute")

        if len(report_ids) != len(set(report_ids)):
            raise CommandError("Report IDs must not be repeated")

        try:
            Team.objects.get(id=team_id)
            reports = [SignalReport.objects.get(id=report_id, team_id=team_id) for report_id in report_ids]
        except Team.DoesNotExist as err:
            raise CommandError(f"Team {team_id} not found") from err
        except (SignalReport.DoesNotExist, ValidationError) as err:
            raise CommandError(f"Every report must exist in team {team_id}") from err

        linked_report_ids = {
            str(report_id)
            for report_id in SignalReportCanvas.objects.for_team(team_id)
            .filter(report_id__in=[report.id for report in reports])
            .values_list("report_id", flat=True)
        }
        eligible_statuses = {SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT}
        eligible_reports = [report for report in reports if report.status in eligible_statuses]

        for report in reports:
            eligibility = "eligible" if report.status in eligible_statuses else "ineligible"
            canvas_state = "linked" if str(report.id) in linked_report_ids else "new"
            self.stdout.write(
                f"{report.id} status={report.status} canvas={canvas_state} {eligibility} title={report.title or 'Untitled report'}"
            )

        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(eligible_reports)} of {len(reports)} selected reports are eligible. "
                    "Run again with --execute to start generation."
                )
            )
            return

        started = 0
        already_running = 0
        for report in eligible_reports:
            workflow_id = SignalReportCanvasWorkflow.workflow_id_for(team_id, str(report.id))
            if async_to_sync(start_report_canvas_workflow)(
                team_id=team_id,
                report_id=str(report.id),
                notify_reviewers=notify_reviewers,
            ):
                started += 1
                self.stdout.write(self.style.SUCCESS(f"Started {report.id} [workflow_id={workflow_id}]"))
            else:
                already_running += 1
                self.stdout.write(self.style.WARNING(f"Already running {report.id} [workflow_id={workflow_id}]"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Started {started}; already running {already_running}; "
                f"skipped {len(reports) - len(eligible_reports)} ineligible reports."
            )
        )
