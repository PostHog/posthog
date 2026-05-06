"""Local dev tool: ingest a saved SignalReport research output as if the agentic flow had just produced it.

Creates a SignalReport row, transitions it through candidate -> in_progress, persists the fixture's
artefacts via `_persist_agentic_report_artefacts` (which is what triggers `_maybe_autostart_task_for_report`),
then transitions the report to READY. Useful for testing the autostart path end-to-end without
running the sandbox research flow.

The fixture shape matches `report_generation/fixtures/analyze_report_funnel_research_output.json`:

    {
      "name": "<human label>",
      "report_id": "<ignored, a fresh UUID is created>",
      "generated_at": "<iso timestamp>",
      "repository": "owner/repo",
      "signal_ids": ["uuid", ...],
      "result": { ReportResearchOutput JSON }
    }
"""

import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalUserAutonomyConfig
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.report import _persist_agentic_report_artefacts


class Command(BaseCommand):
    help = (
        "Ingest a saved SignalReport research output as if the agentic flow had just produced it.\n"
        "Creates a SignalReport, writes the report_generation artefacts, triggers autostart, and marks it READY."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=str,
            help="Path to the report JSON fixture to ingest",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to attach the report to",
        )
        parser.add_argument(
            "--repository",
            type=str,
            default=None,
            help="Override the repository from the fixture (org/repo)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File does not exist: {file_path}")

        try:
            payload = json.loads(file_path.read_text())
        except json.JSONDecodeError as e:
            raise CommandError(f"Fixture is not valid JSON: {file_path}: {e}") from e

        if not isinstance(payload, dict):
            raise CommandError(f"Fixture root must be a JSON object: {file_path}")

        result_payload = payload.get("result")
        if result_payload is None:
            raise CommandError(f"Fixture missing 'result': {file_path}")

        try:
            result = ReportResearchOutput.model_validate(result_payload)
        except Exception as e:
            raise CommandError(f"Fixture 'result' is not a valid ReportResearchOutput: {e}") from e

        repository = options["repository"] or payload.get("repository")
        if not repository:
            raise CommandError("Fixture is missing 'repository' and --repository was not provided")

        try:
            team = Team.objects.select_related("organization").get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        signal_ids = payload.get("signal_ids") or []
        signal_count = max(len(signal_ids), len(result.findings))

        report = self._create_and_advance_report(team, signal_count)

        self.stdout.write(f"Created SignalReport {report.id} for team {team.id} in state {report.status}")
        self.stdout.write(f"Repository: {repository}")
        self.stdout.write(f"Actionability: {result.actionability.actionability.value}")
        if result.priority:
            self.stdout.write(f"Priority: {result.priority.priority.value}")
        else:
            self.stdout.write("Priority: N/A (not actionable)")

        repo_selection = RepoSelectionResult(
            repository=repository,
            reason="ingest_report_json: repository provided by fixture",
        )

        asyncio.run(_persist_agentic_report_artefacts(team.id, str(report.id), result, repo_selection))

        self._finalize_report(report, result)

        self.stdout.write(self.style.SUCCESS(f"Ingested report {report.id} and persisted artefacts."))

        self._warn_if_autonomy_not_configured(team)

    def _create_and_advance_report(self, team: Team, signal_count: int) -> SignalReport:
        with transaction.atomic():
            report = SignalReport.objects.create(
                team=team,
                status=SignalReport.Status.POTENTIAL,
                signal_count=signal_count,
                total_weight=float(signal_count),
            )
            candidate_fields = report.transition_to(SignalReport.Status.CANDIDATE)
            report.save(update_fields=candidate_fields)
            in_progress_fields = report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=3)
            report.save(update_fields=in_progress_fields)
        return report

    def _finalize_report(self, report: SignalReport, result: ReportResearchOutput) -> None:
        with transaction.atomic():
            report.refresh_from_db()
            ready_fields = report.transition_to(SignalReport.Status.READY, title=result.title, summary=result.summary)
            report.save(update_fields=ready_fields)

    def _warn_if_autonomy_not_configured(self, team: Team) -> None:
        from posthog.models import OrganizationMembership

        org_member_user_ids = OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
        ).values_list("user_id", flat=True)
        opted_in_user_count = SignalUserAutonomyConfig.objects.filter(
            user_id__in=org_member_user_ids,
        ).count()
        if not opted_in_user_count:
            self.stdout.write(
                self.style.WARNING(
                    "No org users have a SignalUserAutonomyConfig — autostart will not trigger. "
                    "Opt in via POST /api/users/<id>/signal_autonomy/ first."
                )
            )
