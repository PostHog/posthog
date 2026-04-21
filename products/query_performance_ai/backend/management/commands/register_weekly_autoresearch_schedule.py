"""Register the Temporal schedule that fires WeeklyAutoresearchWorkflow.

Deliberately gated on ``QUERY_PERFORMANCE_AI_ENABLE_SCHEDULE=1`` so a local
dev session running this management command by accident doesn't start firing
weekly sandbox floods.
"""

from __future__ import annotations

import asyncio
import os

from django.core.management.base import BaseCommand, CommandError

from posthog.temporal.common.client import async_connect

from products.query_performance_ai.backend.temporal.schedule import (
    SCHEDULE_ID,
    WEEKLY_CRON,
    create_weekly_autoresearch_schedule,
)
from products.query_performance_ai.backend.temporal.workflows import WeeklyAutoresearchInput


class Command(BaseCommand):
    help = (
        "Register or update the weekly query-performance autoresearch schedule. "
        "Requires QUERY_PERFORMANCE_AI_ENABLE_SCHEDULE=1."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--posthog-team-id",
            type=int,
            required=True,
            help="Team id that owns the weekly run (used for Slack integration lookup).",
        )
        parser.add_argument(
            "--repository",
            default="PostHog/posthog",
            help="Repository the PR-writing sandbox targets (default: PostHog/posthog).",
        )
        parser.add_argument(
            "--branch",
            default=None,
            help="Branch to check out in the sandbox (default: master).",
        )
        parser.add_argument(
            "--slack-channel",
            default="#team-query-performance",
            help="Slack channel for the weekly summary (default: #team-query-performance).",
        )
        parser.add_argument(
            "--candidate-limit",
            type=int,
            default=20,
            help="Max candidates to run per week (default: 20).",
        )

    def handle(self, *args, **options):
        if os.environ.get("QUERY_PERFORMANCE_AI_ENABLE_SCHEDULE") != "1":
            raise CommandError(
                "Schedule registration is gated. Re-run with "
                "QUERY_PERFORMANCE_AI_ENABLE_SCHEDULE=1 if you really want this."
            )

        input_payload = WeeklyAutoresearchInput(
            posthog_team_id=options["posthog_team_id"],
            repository=options["repository"],
            branch=options["branch"],
            slack_channel=options["slack_channel"],
            candidate_limit=options["candidate_limit"],
        )

        self.stdout.write(f"Registering schedule '{SCHEDULE_ID}' (cron: {WEEKLY_CRON})")
        self.stdout.write(f"  team_id={input_payload.posthog_team_id}")
        self.stdout.write(f"  repository={input_payload.repository}")
        self.stdout.write(f"  slack_channel={input_payload.slack_channel}")
        self.stdout.write(f"  candidate_limit={input_payload.candidate_limit}")

        asyncio.run(_register(input_payload))

        self.stdout.write(self.style.SUCCESS("Schedule registered"))


async def _register(input_payload: WeeklyAutoresearchInput) -> None:
    client = await async_connect()
    await create_weekly_autoresearch_schedule(client, input_payload)
