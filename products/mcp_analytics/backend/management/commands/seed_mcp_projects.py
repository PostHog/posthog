import io
import asyncio
import hashlib
from typing import Any

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser

import numpy as np
from temporalio.testing import ActivityEnvironment

from posthog.api.embedding_worker import EmbeddingResponse
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.run_mode import run_mode
from posthog.temporal.mcp_analytics.intent_clustering.activities import compute_intent_clusters_activity
from posthog.temporal.mcp_analytics.intent_clustering.models import IntentClusteringWorkflowInputs

from products.mcp_analytics.backend.management.commands.seed_mcp_sessions import INTENTS_BY_TOOL, TOOL_DESCRIPTIONS

# One project per SDK configuration; None means the SDK isn't installed.
FULL = {"sessions": 800, "days": 28}
BARE = {
    "intent_rate": 0,
    "no_conversation_id": True,
    "no_model": True,
    "anonymous": True,
    "feedback": 0,
    "missing_capabilities": 0,
}
PROJECTS: list[tuple[str, dict[str, Any] | None]] = [
    (
        "MCP: full SDK",
        {"sessions": 2500, "days": 42, "surge_tool": "docs_search", "missing_capabilities": 180, "feedback": 240},
    ),
    ("MCP: early traffic", {"sessions": 30, "max_calls": 6, "days": 10, "feedback": 3, "missing_capabilities": 2}),
    ("MCP: connected, no tool calls", {"sessions": 8, "min_calls": 0, "max_calls": 0, "missing_capabilities": 0}),
    ("MCP: not instrumented", None),
    ("MCP: intent capture off", {**FULL, "intent_rate": 0}),
    ("MCP: partial intent", {**FULL, "intent_rate": 0.3}),
    ("MCP: no conversation IDs", {**FULL, "no_conversation_id": True}),
    ("MCP: no feedback tools", {**FULL, "feedback": 0, "missing_capabilities": 0}),
    ("MCP: no model, anonymous", {**FULL, "no_model": True, "anonymous": True}),
    ("MCP: no errors", {**FULL, "no_errors": True}),
    ("MCP: bare SDK", {**FULL, **BARE}),
    (
        "MCP demo: heavy usage",
        {"sessions": 4000, "days": 42, "surge_tool": "docs_search", "missing_capabilities": 300, "feedback": 400},
    ),
    ("MCP demo: poor instrumentation", {"sessions": 1500, "days": 28, **BARE, "no_client_info": True}),
]

EMBEDDING_DIMENSIONS = 1536


def _direction(key: str) -> np.ndarray:
    vector = np.random.default_rng(int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)).standard_normal(
        EMBEDDING_DIMENSIONS
    )
    return vector / np.linalg.norm(vector)


def fake_embedding(text: str) -> list[float]:
    """Seeded intents and descriptions of one tool share a direction, so they cluster by tool."""
    tool = next((t for t, intents in INTENTS_BY_TOOL.items() if any(i in text for i in intents)), None) or next(
        (t for t, description in TOOL_DESCRIPTIONS.items() if description in text), None
    )
    words = sum((_direction(word) for word in text.lower().split()), np.zeros(EMBEDDING_DIMENSIONS))
    vector = 0.5 * words / (np.linalg.norm(words) or 1) + (0.85 * _direction(tool) if tool else 0)
    return [float(x) for x in vector]


async def _fake_generate_embedding(team: Team, text: str, **_: Any) -> EmbeddingResponse:
    return EmbeddingResponse(embedding=fake_embedding(text), tokens_used=0, did_truncate=False)


async def _skip_cache_write(*_: Any) -> None:
    return None


def cluster_intents(team: Team) -> None:
    # ponytail: the local embedding worker needs an OpenAI key, so the real activity runs on a stand-in embedder.
    with (
        patch("products.mcp_analytics.backend.intent_clustering.async_generate_embedding", _fake_generate_embedding),
        patch("products.mcp_analytics.backend.intent_clustering._persist_embedding", _skip_cache_write),
    ):
        asyncio.run(
            ActivityEnvironment().run(compute_intent_clusters_activity, IntentClusteringWorkflowInputs(team_id=team.id))
        )


class Command(BaseCommand):
    help = "Create one project per MCP SDK configuration in an organization and seed each with MCP analytics data."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--organization-id",
            type=str,
            default=None,
            help="Organization to add the projects to. Defaults to team 1's.",
        )
        parser.add_argument("--only", type=str, default=None, help="Only seed projects whose name contains this text.")

    def handle(self, *args: Any, **options: Any) -> None:
        if run_mode().is_deployed_cloud:
            raise CommandError("seed_mcp_projects writes fabricated data; it does not run on PostHog Cloud.")
        organization = (
            Organization.objects.get(pk=options["organization_id"])
            if options["organization_id"]
            else Team.objects.get(pk=1).organization
        )
        user = organization.members.order_by("id").first()

        for index, (name, seed_options) in enumerate(PROJECTS):
            if options["only"] and options["only"].lower() not in name.lower():
                continue
            team = Team.objects.filter(organization=organization, name=name).first()
            if team is None:
                _, team = Project.objects.create_with_team(organization=organization, name=name, initiating_user=user)
            # --clear with no sessions still removes earlier seeded data from the not-instrumented project.
            call_command(
                "seed_mcp_sessions",
                team_id=team.id,
                clear=True,
                seed=index + 1,
                stdout=io.StringIO(),
                **(seed_options or {"sessions": 0}),
            )
            if seed_options and seed_options.get("max_calls", 1) > 0:
                cluster_intents(team)
            self.stdout.write(self.style.SUCCESS(f"Seeded {name} (team {team.id})"))
