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

    def handle(self, *args, **options) -> None:
        pr_url = options["pr_url"]
        self.stdout.write(self.style.MIGRATE_HEADING(f"ReviewHog ▶ starting · {pr_url}"))
        asyncio.run(main(pr_url=pr_url))
        self.stdout.write(self.style.SUCCESS("ReviewHog ✓ finished"))
