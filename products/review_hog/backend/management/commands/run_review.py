import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.review_hog.backend.temporal.client import execute_review_pr_workflow


class Command(BaseCommand):
    help = "Run a single-turn PR review via the ReviewHog Temporal workflow"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--pr-url",
            required=True,
            type=str,
            help="GitHub PR URL (e.g., https://github.com/PostHog/posthog/pull/34633)",
        )
        parser.add_argument(
            "--team-id",
            required=True,
            type=int,
            help="Team the review runs and persists under",
        )
        parser.add_argument(
            "--user-id",
            required=True,
            type=int,
            help="User the sandbox tasks run as (the PR's author, when triggered in the cloud)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # The CLI only triggers the workflow and blocks for the result — the review runs in the
        # Temporal worker (which needs GITHUB_TOKEN in its env), and stage progress streams there.
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        pr_url = options["pr_url"]
        team_id = options["team_id"]
        user_id = options["user_id"]
        self.stdout.write(self.style.MIGRATE_HEADING(f"ReviewHog ▶ starting · {pr_url} · team {team_id}"))
        report_id = execute_review_pr_workflow(pr_url=pr_url, team_id=team_id, user_id=user_id)
        self.stdout.write(self.style.SUCCESS(f"ReviewHog ✓ finished · report {report_id}"))
