import uuid
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.event.util import create_event
from posthog.models.person.util import create_person, create_person_distinct_id, get_person_by_distinct_id
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT, uuid7
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_person, update_seed_person

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

# Marks events as coming from the new MCP SDK — the tool detail page filters on this.
NEW_SDK_SOURCE = "posthog_mcp_analytics"

# $mcp_tool_category powers the dashboard "share of calls by category" and the tool quality scope filter.
TOOL_CATEGORIES = {
    "query_run": "Querying",
    "insight_get": "Product analytics",
    "dashboard_get": "Product analytics",
    "feature_flag_get": "Feature flags",
    "experiment_get": "Experiments",
    "person_get": "Persons",
    "session_recording_get": "Session replay",
    "error_tracking_issue_get": "Error tracking",
}

TOOL_DESCRIPTIONS = {
    "query_run": "Run a HogQL query against the project's events and return rows.",
    "insight_get": "Fetch a saved insight's definition and computed results.",
    "dashboard_get": "Fetch a dashboard and the insights tiled on it.",
    "feature_flag_get": "Look up a feature flag's configuration and rollout conditions.",
    "experiment_get": "Fetch an experiment's setup and current results.",
    "person_get": "Look up a person and their properties by distinct id.",
    "session_recording_get": "Fetch metadata for a session recording.",
    "error_tracking_issue_get": "Fetch an error-tracking issue and its impact.",
}

# Raw $mcp_client_name values that categorizeHarness() folds into the popular, logo-backed
# harness buckets (Claude Code, OpenAI Codex, Cursor, Claude.ai, VS Code). Weighted toward the
# most common agents so the breakdown looks realistic.
CLIENT_NAMES = ["claude-code", "codex", "cursor", "claude-ai", "visual studio code"]
CLIENT_WEIGHTS = [38, 26, 22, 9, 5]

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

# Paired with a fraction of failing tool calls so the tool detail "Failures" table
# (which reads $exception events) has something to show.
EXCEPTION_MESSAGES: list[str] = [
    "TimeoutError: upstream query exceeded 30s deadline",
    "ValidationError: missing required parameter 'project_id'",
    "PermissionError: API key lacks scope for this resource",
    "ConnectionError: ClickHouse connection reset by peer",
    "KeyError: '$mcp_tool_name' not present in event payload",
]

# Fraction of failing tool calls that also emit a paired $exception event.
EXCEPTION_PAIR_PROBABILITY = 0.6


class Command(BaseCommand):
    help = "Seed $mcp_tool_call events into ClickHouse for local testing of MCP analytics."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to seed events for.")
        parser.add_argument("--sessions", type=int, default=101, help="Number of sessions to create.")
        parser.add_argument("--min-calls", type=int, default=4, help="Minimum tool calls per session (inclusive).")
        parser.add_argument("--max-calls", type=int, default=50, help="Maximum tool calls per session (inclusive).")
        parser.add_argument(
            "--days",
            type=int,
            default=0,
            help="Spread sessions across the last N days (for trend charts). 0 keeps everything in the last hour.",
        )
        parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducible output.")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing $mcp_tool_call events for the team before seeding (clean slate).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        session_count: int = options["sessions"]
        min_calls: int = options["min_calls"]
        max_calls: int = options["max_calls"]
        days: int = options["days"]
        seed: int | None = options["seed"]
        clear: bool = options["clear"]

        if min_calls > max_calls:
            self.stderr.write(self.style.ERROR("--min-calls must be <= --max-calls"))
            return

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist."))
            return

        if clear:
            sync_execute(
                f"ALTER TABLE {EVENTS_DATA_TABLE()} DELETE WHERE team_id = %(team_id)s "
                "AND (event = '$mcp_tool_call' OR (event = '$exception' AND JSONExtractString(properties, '$mcp_tool_name') != '')) "
                "SETTINGS mutations_sync=1",
                {"team_id": team_id},
            )
            with team_scope(team_id):
                MCPSession.objects.filter(team=team).delete()
            self.stdout.write(self.style.WARNING(f"Cleared existing MCP events for team {team_id}."))

        rng = random.Random(seed)
        now = datetime.now(tz=UTC)
        total_events = 0

        # distinct_id -> (person_uuid, person_properties). Events carry person_id so the
        # person-on-events join (Top users table) keeps them — without a real person the
        # inner join drops every row.
        person_cache: dict[str, tuple[str, dict[str, Any]]] = {}

        def ensure_person(
            distinct_id: str, properties: dict[str, Any], is_identified: bool
        ) -> tuple[str, dict[str, Any]]:
            if distinct_id in person_cache:
                return person_cache[distinct_id]
            with personhog_caller_tag("mcp-analytics/seed-sessions"):
                existing_person = get_person_by_distinct_id(
                    team_id=team.id, distinct_id=distinct_id, distinct_id_limit=0
                )
            if existing_person:
                person_uuid = str(existing_person.uuid)
                if properties:
                    with persons_db_connection(writer=True) as conn:
                        update_seed_person(
                            conn,
                            team_id=team.id,
                            uuid=person_uuid,
                            properties=properties,
                            is_identified=is_identified,
                        )
            else:
                person_uuid = str(UUIDT())
                with persons_db_connection(writer=True) as conn:
                    person_id = insert_seed_person(
                        conn,
                        team_id=team.id,
                        properties=properties,
                        is_identified=is_identified,
                        uuid=person_uuid,
                    )
                    insert_seed_distinct_id(conn, team_id=team.id, person_id=person_id, distinct_id=distinct_id)
            create_person(
                team_id=team.id,
                uuid=person_uuid,
                version=0,
                is_identified=is_identified,
                properties=properties,
            )
            create_person_distinct_id(team_id=team.id, distinct_id=distinct_id, person_id=person_uuid)
            person_cache[distinct_id] = (person_uuid, properties)
            return person_cache[distinct_id]

        # Create the identified personas up front (anonymous visitors are created lazily below).
        for persona in IDENTIFIED_PERSONAS:
            ensure_person(
                persona["distinct_id"],
                {"email": persona["email"], "name": persona["name"], "role": persona["role"]},
                is_identified=True,
            )

        for session_idx in range(session_count):
            # $session_id is the canonical session key — the @posthog/mcp SDK emits only
            # this (no $mcp_session_id), so these fixtures mirror a plain SDK-instrumented
            # server. uuid7 matches the PostHog session-id convention.
            session_id = str(uuid7())
            if rng.random() < IDENTIFIED_PROBABILITY:
                persona = rng.choice(IDENTIFIED_PERSONAS)
                distinct_id = persona["distinct_id"]
            else:
                distinct_id = f"anon_{uuid.uuid4().hex[:8]}"
            person_uuid, person_props = ensure_person(distinct_id, {}, is_identified=False)
            client_name = rng.choices(CLIENT_NAMES, weights=CLIENT_WEIGHTS, k=1)[0]
            calls = rng.randint(min_calls, max_calls)
            # Anchor each session within the listing's default 24h window so it shows
            # up on the next request. The listing aggregates recent events on the fly,
            # so any recent session_end works; 31-59 minutes ago keeps the fixtures
            # clearly "in the past" without flirting with the window edge.
            call_intervals = [rng.randint(15, 90) for _ in range(calls)]
            total_call_duration = timedelta(seconds=sum(call_intervals))
            if days > 0:
                # Spread session_end across the last N days so trend charts (bucketed
                # by date over a 7-day window) show a curve instead of a single spike.
                session_end_offset_min = rng.randint(31, days * 24 * 60)
            else:
                session_end_offset_min = rng.randint(31, 59)
            session_start = now - timedelta(minutes=session_end_offset_min) - total_call_duration

            # One coherent intent per session so the clustering page has themes to group.
            primary_tool = rng.choice(TOOL_NAMES)
            session_intent = rng.choice(INTENTS_BY_TOOL.get(primary_tool, [DEFAULT_INTENT]))

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
                create_event(
                    event_uuid=uuid.uuid4(),
                    event="$mcp_tool_call",
                    team=team,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    person_id=uuid.UUID(person_uuid),
                    person_properties=person_props,
                    properties={
                        "$session_id": session_id,
                        "$mcp_source": NEW_SDK_SOURCE,
                        "$mcp_tool_name": tool_name,
                        "$mcp_tool_category": TOOL_CATEGORIES.get(tool_name, "Other"),
                        "$mcp_tool_description": TOOL_DESCRIPTIONS.get(tool_name, ""),
                        "$mcp_intent": session_intent,
                        "$mcp_intent_source": rng.choices(["context_parameter", "inferred"], weights=[7, 3], k=1)[0],
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

                # Pair some failures with an $exception event so the tool detail
                # "Failures" table (which reads $exception events) has data.
                if is_error and rng.random() < EXCEPTION_PAIR_PROBABILITY:
                    create_event(
                        event_uuid=uuid.uuid4(),
                        event="$exception",
                        team=team,
                        distinct_id=distinct_id,
                        timestamp=timestamp,
                        person_id=uuid.UUID(person_uuid),
                        person_properties=person_props,
                        properties={
                            "$session_id": session_id,
                            "$mcp_tool_name": tool_name,
                            "$mcp_client_name": client_name,
                            "$exception_message": rng.choice(EXCEPTION_MESSAGES),
                        },
                    )
                    total_events += 1

            # The session listing derives sessions on the fly from the events above,
            # but intent clustering reads MCPSession.intent (keyed by $session_id), so
            # store one row per session to give the clustering page something to group.
            with team_scope(team_id):
                MCPSession.objects.update_or_create(
                    team=team, session_id=session_id, defaults={"intent": session_intent}
                )
            self.stdout.write(
                f"  session {session_idx + 1}/{session_count}: {calls} tool calls (session_id={session_id})"
            )

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {session_count} sessions ({total_events} events) for team {team_id}.")
        )
