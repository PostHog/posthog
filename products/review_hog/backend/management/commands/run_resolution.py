import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.review_hog.backend.temporal.client import execute_resolution_workflow


class Command(BaseCommand):
    help = "Run the ReviewHog resolution stage on a PR's unresolved review threads via Temporal"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--pr-url",
            required=True,
            type=str,
            help="GitHub PR URL whose unresolved threads to resolve (e.g., https://github.com/PostHog/posthog/pull/72074)",
        )
        parser.add_argument(
            "--team-id",
            required=True,
            type=int,
            help="Team the run executes and persists under",
        )
        parser.add_argument(
            "--user-id",
            required=True,
            type=int,
            help=(
                "User the sandbox session runs as. The CLI also pins this as the acting user, so the run "
                "applies this user's selected resolution criteria."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # The CLI only triggers the workflow and blocks for the result — the resolution runs in the
        # Temporal worker, and per-thread progress streams there. There is no --publish equivalent:
        # this stage's whole job is writing back (replies, resolves, commits), so running it is the consent.
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        pr_url = options["pr_url"]
        team_id = options["team_id"]
        user_id = options["user_id"]
        self.stdout.write(self.style.MIGRATE_HEADING(f"ReviewHog resolution ▶ starting · {pr_url} · team {team_id}"))
        report_id = execute_resolution_workflow(pr_url=pr_url, team_id=team_id, user_id=user_id, acting_user_id=user_id)
        self.stdout.write(self.style.SUCCESS(f"ReviewHog resolution ✓ finished · report {report_id or '(skipped)'}"))
