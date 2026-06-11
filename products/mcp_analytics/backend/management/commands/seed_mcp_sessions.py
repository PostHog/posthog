import uuid
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.models.event.util import create_event
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.util import create_person, create_person_distinct_id, get_person_by_distinct_id
from posthog.models.team.team import Team
from posthog.models.utils import uuid7

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


class Command(BaseCommand):
    help = "Seed mcp_tool_call events into ClickHouse for local testing of MCP analytics."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to seed events for.")
        parser.add_argument("--sessions", type=int, default=101, help="Number of sessions to create.")
        parser.add_argument("--min-calls", type=int, default=4, help="Minimum tool calls per session (inclusive).")
        parser.add_argument("--max-calls", type=int, default=50, help="Maximum tool calls per session (inclusive).")
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

        # Create the identified personas. We write each one to BOTH Postgres
        # (Person + PersonDistinctId) and ClickHouse (via create_person) so the
        # distinct_id -> Person lookup in list_mcp_sessions can resolve name/email.
        for persona in IDENTIFIED_PERSONAS:
            properties = {
                "email": persona["email"],
                "name": persona["name"],
                "role": persona["role"],
            }
            existing_person = get_person_by_distinct_id(team_id=team.id, distinct_id=persona["distinct_id"])
            if existing_person:
                person = existing_person
                person.properties = properties
                person.is_identified = True
                person.save(update_fields=["properties", "is_identified"])
            else:
                person = Person.objects.create(  # nosemgrep: no-direct-persons-db-orm
                    team=team, properties=properties, is_identified=True
                )
                PersonDistinctId.objects.create(  # nosemgrep: no-direct-persons-db-orm
                    team=team, distinct_id=persona["distinct_id"], person=person
                )
            person_uuid = str(person.uuid)
            create_person(
                team_id=team.id,
                uuid=person_uuid,
                version=0,
                is_identified=True,
                properties=properties,
            )
            create_person_distinct_id(
                team_id=team.id,
                distinct_id=persona["distinct_id"],
                person_id=person_uuid,
            )

        for session_idx in range(session_count):
            # $mcp_session_id is the canonical session grouping key emitted by the MCP
            # SDK. Use uuid4 because that's the format the real service emits (e.g.
            # ba10420e-7ff2-4253-a6ac-3e404f14f8be).
            mcp_session_id = str(uuid.uuid4())
            # $session_id keeps the PostHog uuid7 convention so session-replay-style
            # consumers don't choke on it.
            session_id = str(uuid7())
            if rng.random() < IDENTIFIED_PROBABILITY:
                persona = rng.choice(IDENTIFIED_PERSONAS)
                distinct_id = persona["distinct_id"]
            else:
                distinct_id = f"anon_{uuid.uuid4().hex[:8]}"
            client_name = rng.choice(CLIENT_NAMES)
            calls = rng.randint(min_calls, max_calls)
            # Anchor each session within the listing's default 24h window so it shows
            # up on the next request. The listing aggregates recent events on the fly,
            # so any recent session_end works; 31-59 minutes ago keeps the fixtures
            # clearly "in the past" without flirting with the window edge.
            call_intervals = [rng.randint(15, 90) for _ in range(calls)]
            total_call_duration = timedelta(seconds=sum(call_intervals))
            session_end_offset_min = rng.randint(31, 59)
            session_start = now - timedelta(minutes=session_end_offset_min) - total_call_duration

            cumulative_offset_s = 0
            for call_idx in range(calls):
                cumulative_offset_s += call_intervals[call_idx]
                timestamp = session_start + timedelta(seconds=cumulative_offset_s)
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
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$mcp_session_id": mcp_session_id,
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

            # Don't write to MCPSession (it's dormant) — the listing derives sessions
            # on the fly from the events we just captured, grouped by $mcp_session_id.
            self.stdout.write(
                f"  session {session_idx + 1}/{session_count}: {calls} tool calls (mcp_session_id={mcp_session_id})"
            )

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {session_count} sessions ({total_events} events) for team {team_id}.")
        )
