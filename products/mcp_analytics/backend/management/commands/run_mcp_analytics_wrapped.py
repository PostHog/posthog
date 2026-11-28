"""Start the MCP Wrapped coordinator on Temporal, for chosen projects or every project with tool calls in the year."""

import uuid
import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from posthog.temporal.common.client import async_connect

from products.mcp_analytics.backend.temporal.wrapped.constants import COORDINATOR_WORKFLOW_NAME
from products.mcp_analytics.backend.temporal.wrapped.coordinator import WrappedCoordinatorInputs


class Command(BaseCommand):
    help = "Start the MCP Wrapped job on Temporal. Without --team-id it covers every project with tool calls."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--year", type=int, default=None, help="Year to cover. Defaults to the current year.")
        parser.add_argument(
            "--team-id",
            type=int,
            action="append",
            dest="team_ids",
            help="Project (team) ID to generate. Repeat it for several projects.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        inputs = WrappedCoordinatorInputs(year=options["year"], team_ids=options["team_ids"])
        workflow_id = f"{COORDINATOR_WORKFLOW_NAME}-{uuid.uuid4().hex[:12]}"

        async def _start() -> None:
            # async_connect, because asyncio.run already owns the event loop and sync_connect cannot nest one.
            client = await async_connect()
            await client.start_workflow(
                COORDINATOR_WORKFLOW_NAME, inputs, id=workflow_id, task_queue=settings.MCPA_TASK_QUEUE
            )

        asyncio.run(_start())
        self.stdout.write(
            self.style.SUCCESS(f"Started {workflow_id} on {settings.MCPA_TASK_QUEUE}. Follow it in the Temporal UI.")
        )
