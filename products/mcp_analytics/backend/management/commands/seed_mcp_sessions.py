import uuid
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.models.event.util import create_event
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

        for session_idx in range(session_count):
            session_id = str(uuid7())
            distinct_id = f"seed_user_{uuid.uuid4().hex[:8]}"
            client_name = rng.choice(CLIENT_NAMES)
            calls = rng.randint(min_calls, max_calls)
            # Spread the session across a 5-minute window, anchored a random number of hours in the past.
            session_start = now - timedelta(hours=rng.randint(0, 48), minutes=rng.randint(0, 59))

            for call_idx in range(calls):
                timestamp = session_start + timedelta(seconds=call_idx * rng.randint(15, 90))
                create_event(
                    event_uuid=uuid.uuid4(),
                    event="mcp_tool_call",
                    team=team,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$mcp_tool_name": rng.choice(TOOL_NAMES),
                        "$mcp_client_name": client_name,
                        "$mcp_client_version": "1.0.0",
                        "$mcp_protocol_version": "2025-03-26",
                        "$mcp_transport": "streamable_http",
                    },
                )
                total_events += 1

            self.stdout.write(f"  session {session_idx + 1}/{session_count}: {calls} tool calls ({session_id})")

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {session_count} sessions ({total_events} events) for team {team_id}.")
        )
