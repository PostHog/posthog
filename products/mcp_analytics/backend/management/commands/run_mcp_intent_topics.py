"""Run one intent topics pipeline step for a team through Temporal and print the run summary.

Requires a running Temporal worker on ``settings.MCPA_TASK_QUEUE`` (``hogli start`` provides one).
A first-time bootstrap is ``sync`` (wait for the embedding worker), then ``refit``, then ``assign``.
"""

import time
import uuid
import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.temporal.common.client import async_connect
from posthog.temporal.mcp_analytics.intent_topics.constants import CHILD_WORKFLOW_ID_PREFIX, WORKFLOW_NAME
from posthog.temporal.mcp_analytics.intent_topics.models import (
    RUN_KINDS,
    IntentTopicsWorkflowInputs,
    IntentTopicsWorkflowResult,
)

from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic


class Command(BaseCommand):
    help = "Run the intent topics sync, assign or refit step for a team and print the result."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--kind", choices=RUN_KINDS, default="sync")
        parser.add_argument("--now", default="", help="ISO timestamp to run as; defaults to the wall clock.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        kind: str = options["kind"]
        if not Team.objects.filter(pk=team_id).exists():
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist."))
            return

        self.stdout.write(f"Running intent topics '{kind}' for team {team_id} on {settings.MCPA_TASK_QUEUE}...")
        inputs = IntentTopicsWorkflowInputs(team_id=team_id, kind=kind, now=options["now"])
        workflow_id = (
            f"{CHILD_WORKFLOW_ID_PREFIX}-{team_id}-{kind}-cli-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        )

        async def _run() -> Any:
            client = await async_connect()
            return await client.execute_workflow(
                WORKFLOW_NAME,
                inputs,
                id=workflow_id,
                task_queue=settings.MCPA_TASK_QUEUE,
                result_type=IntentTopicsWorkflowResult,
            )

        result = asyncio.run(_run())
        for run in result.runs:
            style = self.style.SUCCESS if run.status == "succeeded" else self.style.WARNING
            self.stdout.write(
                style(
                    f"{run.kind}: {run.status} run_id={run.run_id} intents={run.n_intents} topics={run.n_topics} "
                    f"outliers={run.n_outliers} embeddings_requested={run.n_embeddings_requested} {run.error_message}"
                )
            )

        with team_scope(team_id):
            topics = list(MCPIntentTopic.active.filter(team_id=team_id).order_by("-member_count")[:20])
            last_runs = list(MCPIntentClusteringRun.objects.filter(team_id=team_id).order_by("-started_at")[:5])
        if topics:
            self.stdout.write("\nActive topics (top 20 by members):")
            for topic in topics:
                self.stdout.write(
                    f"  [{str(topic.pk)[:8]}] {topic.label!r} members={topic.member_count} outlier_distance={topic.outlier_distance:.3f}"
                )
        self.stdout.write("\nRecent runs:")
        for run in last_runs:
            self.stdout.write(
                f"  {run.kind:6} {run.status:18} {run.run_id} intents={run.n_intents} topics={run.n_topics}"
            )
