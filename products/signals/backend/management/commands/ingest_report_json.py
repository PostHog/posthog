"""Local dev tool: ingest a saved SignalReport research output via emit_report().

Parses the fixture, extracts the title, summary, actionability, and priority from the
ReportResearchOutput, then calls emit_report() which starts the EmitReportWorkflow.
The workflow handles report creation, repo selection, enrichment, artefact persistence,
auto-start checks, and final state transitions.

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

from posthog.models import Team

from products.signals.backend.report_generation.research import ActionabilityChoice, Priority, ReportResearchOutput


class Command(BaseCommand):
    help = (
        "Ingest a saved SignalReport research output via emit_report().\n"
        "Parses the fixture and calls emit_report() to start the EmitReportWorkflow."
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

        try:
            team = Team.objects.select_related("organization").get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        actionability = result.actionability.actionability
        actionability_explanation = result.actionability.explanation

        # emit_report requires a priority — fall back to P4 for not-actionable fixtures
        # that omit it, since the workflow will reset them to potential anyway.
        if result.priority:
            priority = result.priority.priority
            priority_explanation = result.priority.explanation
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Fixture has no priority assessment — defaulting to P4. (actionability: {actionability.value})"
                )
            )
            priority = Priority.P4
            priority_explanation = "Default P4: fixture did not include a priority assessment."

        self.stdout.write(f"Title: {result.title}")
        self.stdout.write(f"Actionability: {actionability.value}")
        self.stdout.write(f"Priority: {priority.value}")

        report_id = asyncio.run(
            self._emit(team, result, actionability, actionability_explanation, priority, priority_explanation)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Started EmitReportWorkflow for report {report_id}. "
                "The workflow will handle repo selection, enrichment, artefact persistence, and state transitions."
            )
        )

    async def _emit(
        self,
        team: Team,
        result: ReportResearchOutput,
        actionability: ActionabilityChoice,
        actionability_explanation: str,
        priority: Priority,
        priority_explanation: str,
    ) -> str:
        from products.signals.backend.api import emit_report

        return await emit_report(
            team=team,
            title=result.title,
            summary=result.summary,
            actionability=actionability,
            actionability_explanation=actionability_explanation,
            priority=priority,
            priority_explanation=priority_explanation,
        )
