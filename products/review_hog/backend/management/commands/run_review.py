import asyncio

from django.core.management.base import BaseCommand, CommandParser

from products.review_hog.backend.reviewer.run import main


class Command(BaseCommand):
    help = "Run a multi-pass PR review using sandbox agents"

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

    def handle(self, *args, **options) -> None:
        pr_url = options["pr_url"]
        team_id = options["team_id"]
        user_id = options["user_id"]
        self.stdout.write(self.style.MIGRATE_HEADING(f"ReviewHog ▶ starting · {pr_url} · team {team_id}"))
        asyncio.run(main(pr_url=pr_url, team_id=team_id, user_id=user_id))
        self.stdout.write(self.style.SUCCESS("ReviewHog ✓ finished"))
