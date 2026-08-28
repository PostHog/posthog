"""Manual end-to-end validation for the intent clustering pipeline.

Starts a one-off ``DailyIntentClusteringWorkflow`` execution and waits for
it, then pretty-prints the resulting snapshot. Requires a running Temporal
worker on ``settings.MCPA_TASK_QUEUE`` (provided locally by ``hogli start``).
"""

import json
import time
import uuid
import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.temporal.common.client import async_connect
from posthog.temporal.mcp_analytics.intent_clustering.constants import CHILD_WORKFLOW_ID_PREFIX, WORKFLOW_NAME
from posthog.temporal.mcp_analytics.intent_clustering.models import IntentClusteringWorkflowInputs

from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot


class Command(BaseCommand):
    help = "Run intent clustering for a team and pretty-print the resulting snapshot."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to cluster intents for.")
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=None,
            help="Window for both the session and ClickHouse queries. Default uses the task default (7 days).",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print the raw JSON snapshot instead of the human-readable summary.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        lookback_days: int | None = options["lookback_days"]
        raw: bool = options["raw"]

        try:
            Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist."))
            return

        window_label = f"{lookback_days} day(s)" if lookback_days is not None else "default window"
        self.stdout.write(
            f"Running intent clustering for team {team_id} ({window_label}) via Temporal "
            f"on {settings.MCPA_TASK_QUEUE}..."
        )

        workflow_inputs = IntentClusteringWorkflowInputs(
            team_id=team_id,
            **({"lookback_days": lookback_days} if lookback_days is not None else {}),
        )
        workflow_id = f"{CHILD_WORKFLOW_ID_PREFIX}-{team_id}-cli-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        async def _run() -> None:
            # async_connect() must be used here — we're already inside
            # an event loop via asyncio.run(_run()), and sync_connect()
            # wraps async_to_sync which can't nest event loops.
            client = await async_connect()
            await client.execute_workflow(
                WORKFLOW_NAME,
                workflow_inputs,
                id=workflow_id,
                task_queue=settings.MCPA_TASK_QUEUE,
            )

        asyncio.run(_run())

        with team_scope(team_id):
            snapshot = MCPIntentClusterSnapshot.objects.filter(team_id=team_id).first()
        if snapshot is None:
            self.stderr.write(self.style.ERROR("No snapshot was produced."))
            return

        if snapshot.status == MCPIntentClusterSnapshot.Status.ERROR:
            self.stderr.write(self.style.ERROR(f"Clustering failed: {snapshot.error_message}"))
            return

        if raw:
            self.stdout.write(json.dumps(snapshot.clusters, indent=2))
            return

        self._print_summary(snapshot)

    def _print_summary(self, snapshot: MCPIntentClusterSnapshot) -> None:
        blob = snapshot.clusters or {}
        clusters = blob.get("clusters", [])
        meta = blob.get("computed_with", {}) or {}

        self.stdout.write(self.style.SUCCESS("✔ Clustering complete"))
        self.stdout.write(
            f"  computed_at: {snapshot.last_computed_at.isoformat() if snapshot.last_computed_at else '—'}"
        )
        self.stdout.write(f"  embedding_model: {meta.get('embedding_model', '—')}")
        self.stdout.write(f"  distance_threshold: {meta.get('distance_threshold', '—')}")
        self.stdout.write(f"  n_intents in corpus: {meta.get('n_intents', 0)}")
        self.stdout.write(f"  n_clusters produced: {meta.get('n_clusters', 0)}")

        if not clusters:
            self.stdout.write(self.style.WARNING("\nNo clusters — likely no $mcp_tool_call events with $mcp_intent."))
            self.stdout.write("Try: ./manage.py seed_mcp_sessions --team-id N")
            return

        self.stdout.write("\nClusters (sorted by call volume):\n")
        for cluster in clusters:
            self.stdout.write(self.style.HTTP_INFO(f"  [{cluster['id']}] {cluster['label']!r}"))
            self.stdout.write(
                f"      intents: {cluster['intent_count']}  calls: {cluster['call_count']}  "
                f"errors: {cluster['error_count']} ({cluster['error_rate_pct']}%)  "
                f"routing_entropy: {cluster['routing_entropy']}"
            )
            tool_rows = cluster.get("tool_distribution", [])
            for entry in tool_rows[:5]:
                self.stdout.write(
                    f"        → {entry['tool']}: {entry['count']} calls "
                    f"({entry['pct']}%), errors {entry['errors']} ({entry['error_rate_pct']}%)"
                )
            if len(tool_rows) > 5:
                self.stdout.write(f"        … and {len(tool_rows) - 5} more tools")
            for sample in cluster.get("sample_intents", []):
                self.stdout.write(f"        ✎ {sample}")
            self.stdout.write("")
