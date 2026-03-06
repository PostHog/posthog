import asyncio

from django.core.management.base import BaseCommand

from products.review_hog.backend.reviewer.run import main


class Command(BaseCommand):
    help = "Run a multi-pass PR review using sandbox agents"

    def add_arguments(self, parser):
        parser.add_argument(
            "--pr-url",
            required=True,
            type=str,
            help="GitHub PR URL (e.g., https://github.com/PostHog/posthog/pull/34633)",
        )

    def handle(self, *args, **options):
        asyncio.run(main(pr_url=options["pr_url"]))
