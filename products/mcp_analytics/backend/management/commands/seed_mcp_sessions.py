import uuid
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.models.event.util import create_event
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.team.team import Team
from posthog.models.utils import uuid7

from products.mcp_analytics.backend.models import MCPSession

TOOL_NAMES = [
    "query_run",
    "insight_get",
    "dashboard_get",
    "feature_flag_get",
    "experiment_get",
    "person_get",
    "session_recording_get",
    "error_tracking_issue_get",
]

CLIENT_NAMES = ["Claude Desktop", "Cursor", "Windsurf", "Cline"]

# Identified personas. About 70% of sessions are attached to one of these;
# the rest stay anonymous with throwaway distinct_ids.
IDENTIFIED_PERSONAS: list[dict[str, str]] = [
    {
        "distinct_id": "alice@hedgehog.dev",
        "email": "alice@hedgehog.dev",
        "name": "Alice Hedgehog",
        "role": "Product engineer",
    },
    {"distinct_id": "ben@hedgehog.dev", "email": "ben@hedgehog.dev", "name": "Ben Hedgehog", "role": "Data scientist"},
    {
        "distinct_id": "carol@hedgehog.dev",
        "email": "carol@hedgehog.dev",
        "name": "Carol Hedgehog",
        "role": "Product manager",
    },
    {
        "distinct_id": "dan@hedgehog.dev",
        "email": "dan@hedgehog.dev",
        "name": "Dan Hedgehog",
        "role": "Engineering manager",
    },
]
IDENTIFIED_PROBABILITY = 0.7

INTENTS_BY_TOOL: dict[str, list[str]] = {
    "query_run": [
        "Investigating yesterday's spike in checkout failures by querying revenue and error events for the last 24 hours.",
        "Pulling the funnel conversion numbers for the new pricing page to share in the product weekly review.",
        "Validating that the latest deploy did not regress signup completion rate before announcing the release.",
    ],
    "insight_get": [
        "Fetching the active users dashboard insight to summarise growth trends in the leadership Slack channel.",
        "Loading the retention curve insight so we can compare last cohort to the previous one in the product review.",
    ],
    "dashboard_get": [
        "Opening the platform health dashboard to triage user-reported latency complaints from this morning.",
    ],
    "feature_flag_get": [
        "Checking whether the new pricing flag is rolled out to the cohort experiencing the support issue.",
    ],
    "experiment_get": [
        "Reviewing the running pricing experiment to decide whether we have enough power to call a winner this week.",
    ],
    "person_get": [
        "Looking up the reporter of a paid plan billing complaint to confirm their plan history before refunding.",
    ],
    "session_recording_get": [
        "Replaying the session where the user got stuck on signup to understand the friction point before filing a bug.",
    ],
    "error_tracking_issue_get": [
        "Pulling the latest exception issue tied to the deploy so the on-call can triage the regression quickly.",
    ],
}
DEFAULT_INTENT = "Helping the user investigate a recent product-analytics question without a specific recorded intent."


# Session-level summarised intents. These intentionally repeat themes so the
# clustering pipeline has something to cluster: variants of "check a feature
# flag rollout" should land in one cluster, variants of "look up the reporter
# of a billing issue" in another, etc.
SESSION_INTENTS: list[str] = [
    "Investigate yesterday's spike in checkout failures using revenue and error events.",
    "Look into the unusual drop in checkout completion that started overnight.",
    "Pull funnel conversion numbers for the new pricing page for the weekly product review.",
    "Compare pricing page funnel performance week over week ahead of the product review.",
    "Check whether the new pricing feature flag is fully rolled out to the affected cohort.",
    "Confirm rollout status of the pricing feature flag for a support escalation.",
    "Review the active pricing experiment and decide whether we have the power to call a winner.",
    "Pull active users metrics to share growth trends in the leadership Slack channel.",
    "Compare last cohort's retention curve to the previous one for the product review.",
    "Triage user-reported latency complaints from this morning using the platform health dashboard.",
    "Look up the reporter of a paid plan billing complaint before processing a refund.",
    "Replay the signup session where the user got stuck so we can file a precise bug report.",
    "Pull the latest exception issue tied to the deploy so on-call can triage the regression.",
]
CONVERSATION_CONTINUE_PROBABILITY = 0.4


class Command(BaseCommand):
    help = "Seed mcp_tool_call events into ClickHouse for local testing of MCP analytics."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to seed events for.")
        parser.add_argument("--sessions", type=int, default=10, help="Number of sessions to create.")
        parser.add_argument("--min-calls", type=int, default=4, help="Minimum tool calls per session (inclusive).")
        parser.add_argument("--max-calls", type=int, default=6, help="Maximum tool calls per session (inclusive).")
        parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducible output.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        session_count: int = options["sessions"]
        min_calls: int = options["min_calls"]
        max_calls: int = options["max_calls"]
        seed: int | None = options["seed"]

        if min_calls > max_calls:
            self.stderr.write(self.style.ERROR("--min-calls must be <= --max-calls"))
            return

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist."))
            return

        rng = random.Random(seed)
        now = datetime.now(tz=UTC)
        total_events = 0

        # Create the identified personas and remember each one's person_id so
        # we can stamp it on every event tied to that persona.
        persona_person_ids: dict[str, str] = {}
        for persona in IDENTIFIED_PERSONAS:
            person_uuid = create_person(
                team_id=team.id,
                version=0,
                is_identified=True,
                properties={
                    "email": persona["email"],
                    "name": persona["name"],
                    "role": persona["role"],
                },
            )
            create_person_distinct_id(
                team_id=team.id,
                distinct_id=persona["distinct_id"],
                person_id=person_uuid,
            )
            persona_person_ids[persona["distinct_id"]] = person_uuid

        active_conversation_id: str | None = None
        for session_idx in range(session_count):
            session_id = str(uuid7())
            if active_conversation_id and rng.random() < CONVERSATION_CONTINUE_PROBABILITY:
                conversation_id = active_conversation_id
            else:
                conversation_id = str(uuid7())
                active_conversation_id = conversation_id
            if rng.random() < IDENTIFIED_PROBABILITY:
                persona = rng.choice(IDENTIFIED_PERSONAS)
                distinct_id = persona["distinct_id"]
                person_id: uuid.UUID | None = uuid.UUID(persona_person_ids[distinct_id])
            else:
                distinct_id = f"anon_{uuid.uuid4().hex[:8]}"
                person_id = None
            client_name = rng.choice(CLIENT_NAMES)
            calls = rng.randint(min_calls, max_calls)
            # Spread the session across a 5-minute window, anchored a random number of hours in the past.
            session_start = now - timedelta(hours=rng.randint(0, 48), minutes=rng.randint(0, 59))
            session_intent = rng.choice(SESSION_INTENTS)
            MCPSession.objects.create(
                team=team,
                session_id=session_id,
                conversation_id=conversation_id,
                intent=session_intent,
            )

            for call_idx in range(calls):
                timestamp = session_start + timedelta(seconds=call_idx * rng.randint(15, 90))
                tool_name = rng.choice(TOOL_NAMES)
                # Skew error rate and latency per tool so the Tool quality tab has variation.
                tool_error_rate = (hash(tool_name) % 30) / 100.0
                is_error = rng.random() < tool_error_rate
                base_latency = 80 + (hash(tool_name) % 400)
                duration_ms = max(1, int(rng.gauss(base_latency, base_latency * 0.4)))
                if is_error:
                    duration_ms = int(duration_ms * rng.uniform(1.5, 3.0))
                intent = rng.choice(INTENTS_BY_TOOL.get(tool_name, [DEFAULT_INTENT]))
                create_event(
                    event_uuid=uuid.uuid4(),
                    event="mcp_tool_call",
                    team=team,
                    distinct_id=distinct_id,
                    person_id=person_id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$mcp_tool_name": tool_name,
                        "$mcp_intent": intent,
                        "$mcp_error_message": "Upstream returned 500" if is_error else "",
                        "$mcp_client_name": client_name,
                        "$mcp_client_version": "1.0.0",
                        "$mcp_protocol_version": "2025-03-26",
                        "$mcp_transport": "streamable_http",
                        "$mcp_duration_ms": duration_ms,
                        "$mcp_is_error": is_error,
                    },
                )
                total_events += 1

            self.stdout.write(f"  session {session_idx + 1}/{session_count}: {calls} tool calls ({session_id})")

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {session_count} sessions ({total_events} events) for team {team_id}.")
        )
