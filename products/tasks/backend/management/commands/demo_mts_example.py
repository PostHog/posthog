from __future__ import annotations

import time
import asyncio
import traceback
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.report_generation.research import ReportResearchOutput
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext
from products.tasks.backend.services.mts_example import run_cursed_identifier_research

REPOSITORY = "PostHog/posthog"
BRANCH = "master"


class Command(BaseCommand):
    help = (
        "Demo: run MultiTurnSession against PostHog/posthog to research the most 'cursed' "
        "identifiers and stale comments, returning output in the shape Signals consumes. "
        "See products/tasks/backend/services/mts_example/README.md. DEBUG only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID")
        parser.add_argument("--user-id", type=int, required=True, help="User ID")
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream raw sandbox log lines instead of only agent messages",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("demo_mts_example only runs with DEBUG=1")

        team_id = options["team_id"]
        user_id = options["user_id"]
        verbose = options["verbose"]

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team {team_id} not found")
        if not User.objects.filter(id=user_id).exists():
            raise CommandError(f"User {user_id} not found")

        context = CustomPromptSandboxContext(
            team_id=team_id,
            user_id=user_id,
            repository=REPOSITORY,
            posthog_mcp_scopes="read_only",
        )

        self.stdout.write(f"Repository: {REPOSITORY} (branch: {BRANCH})")
        self.stdout.write(f"Team: {team_id}  User: {user_id}")
        self.stdout.write("Starting cursed identifier research...")
        self.stdout.write("")

        try:
            result = asyncio.run(
                run_cursed_identifier_research(
                    context,
                    branch=BRANCH,
                    verbose=verbose,
                    output_fn=self._flushing_write,
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed: {e}"))
            self.stdout.write(traceback.format_exc())
            raise

        self._print_result(result)
        self._write_json(result)

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def _print_result(self, result: ReportResearchOutput) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS(f"Title:   {result.title}"))
        self.stdout.write(f"Summary: {result.summary}")
        self.stdout.write("")
        self.stdout.write(
            f"Actionability: {result.actionability.actionability.value} "
            f"(already_addressed={result.actionability.already_addressed})"
        )
        self.stdout.write(f"  Reason: {result.actionability.explanation}")
        if result.priority:
            self.stdout.write(f"Priority: {result.priority.priority.value}")
            self.stdout.write(f"  Reason: {result.priority.explanation}")
        else:
            self.stdout.write("Priority: N/A (not actionable)")
        self.stdout.write("")
        for i, finding in enumerate(result.findings, start=1):
            self.stdout.write(self.style.WARNING(f"--- Finding {i}/{len(result.findings)} ({finding.signal_id}) ---"))
            self.stdout.write(f"  Paths: {', '.join(finding.relevant_code_paths) or '(none)'}")
            self.stdout.write(f"  Verified: {finding.verified}")
            for sha, reason in finding.relevant_commit_hashes.items():
                self.stdout.write(f"  {sha}: {reason}")
            self.stdout.write(f"  MCP/data: {finding.data_queried}")
            self.stdout.write("")

    def _write_json(self, result: ReportResearchOutput) -> None:
        path = Path(f"mts_example_{int(time.time())}.json")
        path.write_text(result.model_dump_json(indent=2))
        self.stdout.write(self.style.SUCCESS(f"Saved: {path}"))
