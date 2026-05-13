"""Local dev tool for manually testing the internal-user referral research agent. DEBUG only.

Queries PostHog behavioural data through a sandbox agent and prints the filtered referral candidates.
Intended for prompt iteration; the production version will be scheduled separately from the Twitter flow.
"""

import asyncio
import logging
import dataclasses

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.referrals.backend.internal.research.research import run_internal_research
from products.tasks.backend.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev

logger = logging.getLogger(__name__)

# Small dummy repo: the agent only needs MCP execute-sql, not the PostHog source tree.
DEFAULT_REPOSITORY = "PostHog/.github"


class Command(BaseCommand):
    help = "Local dev tool: run the internal-user referral research agent once. DEBUG only."

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def add_arguments(self, parser):
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

        verbose: bool = options["verbose"]
        repository: str = options["repository"]

        try:
            base_context = resolve_sandbox_context_for_local_dev(repository)
        except RuntimeError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        # The default resolver does not set MCP scopes — internal flow needs `execute-sql`,
        # so we layer them on with a frozen-dataclass replace.
        context = dataclasses.replace(base_context, posthog_mcp_scopes="read_only")

        self.stdout.write(f"Repository: {repository}")
        self.stdout.write(f"MCP scopes: {context.posthog_mcp_scopes}")
        self.stdout.write("")

        result = asyncio.run(
            run_internal_research(
                context,
                verbose=verbose,
                output_fn=self._flushing_write,
            )
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"=== Result: {len(result.candidates)} candidate(s) ==="))
        for candidate in result.candidates:
            org = candidate.org_name or candidate.org_id or "<no org>"
            self.stdout.write(f"  {candidate.email or '<no email>'}  ({org})")
            self.stdout.write(f"    distinct_id: {candidate.distinct_id}")
            self.stdout.write(f"    {candidate.reason}")
