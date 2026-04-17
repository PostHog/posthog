from __future__ import annotations

import json
import time
import asyncio
import traceback
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team
from posthog.models.user import User

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
            findings, actionability, priority, presentation = asyncio.run(
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

        self._print_result(findings, actionability, priority, presentation)
        self._write_json(findings, actionability, priority, presentation)

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def _print_result(self, findings, actionability, priority, presentation) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS(f"Title:   {presentation.title}"))
        self.stdout.write(f"Summary: {presentation.summary}")
        self.stdout.write("")
        self.stdout.write(
            f"Actionability: {actionability.actionability.value} (already_addressed={actionability.already_addressed})"
        )
        self.stdout.write(f"  Reason: {actionability.explanation}")
        if priority:
            self.stdout.write(f"Priority: {priority.priority.value}")
            self.stdout.write(f"  Reason: {priority.explanation}")
        else:
            self.stdout.write("Priority: N/A (not actionable)")
        self.stdout.write("")
        for i, finding in enumerate(findings, start=1):
            self.stdout.write(self.style.WARNING(f"--- Finding {i}/{len(findings)} ({finding.signal_id}) ---"))
            self.stdout.write(f"  Paths: {', '.join(finding.relevant_code_paths) or '(none)'}")
            self.stdout.write(f"  Verified: {finding.verified}")
            for sha, reason in finding.relevant_commit_hashes.items():
                self.stdout.write(f"  {sha}: {reason}")
            self.stdout.write(f"  MCP/data: {finding.data_queried}")
            self.stdout.write("")

    def _write_json(self, findings, actionability, priority, presentation) -> None:
        payload = {
            "findings": [f.model_dump(mode="json") for f in findings],
            "actionability": actionability.model_dump(mode="json"),
            "priority": priority.model_dump(mode="json") if priority else None,
            "presentation": presentation.model_dump(mode="json"),
        }
        path = Path(f"mts_example_{int(time.time())}.json")
        path.write_text(json.dumps(payload, indent=2, default=str))
        self.stdout.write(self.style.SUCCESS(f"Saved: {path}"))
