"""Local dev tool for manually testing the Twitter referral research agent. DEBUG only.

Fetches recent PostHog tweets through a sandbox agent and prints the filtered referral candidates.
Intended for prompt iteration; the production version will be scheduled via a Temporal cron.
"""

import os
import time
import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.referrals.backend.twitter.research.research import run_twitter_research
from products.tasks.backend.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev

logger = logging.getLogger(__name__)

# Small dummy repo: the agent only needs curl/jq, not the PostHog source tree.
DEFAULT_REPOSITORY = "PostHog/.github"
DEFAULT_HOURS = 1


class Command(BaseCommand):
    help = "Local dev tool: run the Twitter referral research agent once. DEBUG only."

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=DEFAULT_HOURS,
            help=f"Look back this many hours when fetching tweets (default: {DEFAULT_HOURS})",
        )
        parser.add_argument(
            "--repository",
            type=str,
            default=DEFAULT_REPOSITORY,
            help=f"GitHub repository for sandbox bootstrap (default: {DEFAULT_REPOSITORY})",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream full raw S3 log lines instead of only agent messages",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        api_key = os.environ.get("TWITTERAPI_IO_KEY")
        if not api_key:
            raise CommandError("TWITTERAPI_IO_KEY is not set in the environment")

        hours: int = options["hours"]
        verbose: bool = options["verbose"]
        repository: str = options["repository"]

        if hours <= 0:
            raise CommandError("--hours must be a positive integer")

        since_unix_ts = int(time.time()) - hours * 3600

        try:
            context = resolve_sandbox_context_for_local_dev(repository)
        except RuntimeError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(f"Hours: {hours}")
        self.stdout.write(f"Since unix ts: {since_unix_ts}")
        self.stdout.write(f"Repository: {repository}")
        self.stdout.write("")

        result = asyncio.run(
            run_twitter_research(
                context,
                api_key=api_key,
                since_unix_ts=since_unix_ts,
                hours=hours,
                verbose=verbose,
                output_fn=self._flushing_write,
            )
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"=== Result: {len(result.candidates)} candidate(s) ==="))
        for candidate in result.candidates:
            self.stdout.write(f"  {candidate.id}  @{candidate.user}")
            self.stdout.write(f"    {candidate.reason}")
