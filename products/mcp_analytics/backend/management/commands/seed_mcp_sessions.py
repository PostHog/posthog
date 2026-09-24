import uuid
import zlib
import random
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from django.core.management.base import BaseCommand, CommandParser

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.models.event.deletion import events_data_tables_via_sync_execute, events_read_tables_via_sync_execute
from posthog.models.event.util import create_event
from posthog.models.person.missing_person import uuidFromDistinctId
from posthog.models.person.util import create_person, create_person_distinct_id, get_person_by_distinct_id
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT, uuid7
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_person, update_seed_person

from products.mcp_analytics.backend.models import MCPSession

# Weighted like real traffic, where a few tools take most calls, so the tool breakdown has a long tail.
TOOL_WEIGHTS: dict[str, int] = {
    "query_run": 34,
    "insight_get": 22,
    "dashboard_get": 14,
    "feature_flag_get": 10,
    "error_tracking_issue_get": 8,
    "person_get": 6,
    "experiment_get": 4,
    "session_recording_get": 2,
}
TOOL_NAMES = list(TOOL_WEIGHTS)

MISSING_CAPABILITY_TOOL_NAME = "get_more_tools"

# Advertised in $mcp_tools_list but never called, so the seeded catalog holds more tools than agents use.
UNCALLED_TOOL_NAMES = ["annotation_create", "cohort_get"]

# Marks events as coming from the new MCP SDK — the tool detail page filters on this.
NEW_SDK_SOURCE = "posthog_mcp_analytics"
MCP_SERVER_NAME = "posthog-mcp"
MCP_SERVER_VERSION = "2.14.0"
# The 2026-07-28 revision removed protocol sessions: no initialize handshake and no Mcp-Session-Id.
# Each seeded session speaks one revision, so a session is either all legacy or all stateless.
LEGACY_PROTOCOL_VERSION = "2025-11-25"
STATELESS_PROTOCOL_VERSION = "2026-07-28"
STATELESS_SESSION_PROBABILITY = 0.45
SDK_LIB_NAME = "posthog-node-mcp"

# Every seeded event carries this marker so --clear can target exactly what this
# command created, never genuine SDK traffic sharing the same event names.
SEEDED_MARKER_PROPERTY = "$mcp_seeded"
SEEDED_EVENT_NAMES = (
    "$mcp_initialize",
    "$mcp_tools_list",
    "$mcp_tool_call",
    "$mcp_missing_capability",
    "$exception",
)


def _fnv1a_hex(value: str) -> str:
    # 64-bit FNV-1a as two 32-bit halves, matching `ids.ts` in @posthog/mcp bit for bit.
    h1, h2 = 0x84222325, 0xCBF29CE4
    for char in value:
        h1 = ((h1 ^ ord(char)) * 0x1B3) & 0xFFFFFFFF
        h2 = ((h2 ^ ord(char)) * 0x193) & 0xFFFFFFFF
    return f"{h1:08x}{h2:08x}"


def session_id_from_conversation(conversation_id: str) -> str:
    """The $session_id the SDK derives from a conversation id (`deriveSessionIdFromConversation`)."""
    return f"ses_{_fnv1a_hex(conversation_id)}{_fnv1a_hex(f'{conversation_id}::salt')}"


def stable_hash(value: str) -> int:
    # Not hash(): that's salted per process, which would change how many RNG draws
    # each session consumes and break --seed reproducibility across invocations.
    return zlib.crc32(value.encode())


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


@frozen
class _ClientProfile:
    name: str
    version: str
    # The x-anthropic-client header. Only Anthropic clients send it.
    vendor_client: str | None
    user_agent: str | None
    models: list[str]
    # Codex puts the model in request metadata. Other agents report it through the injected llm_model argument.
    model_source: Literal["client_metadata", "self_reported"]
    weight: int


CLIENT_PROFILES: list[_ClientProfile] = [
    _ClientProfile(
        name="claude-code",
        version="2.1.12",
        vendor_client="claude-code",
        user_agent="claude-code/2.1.12 (cli)",
        models=["claude-opus-5-5", "claude-sonnet-5"],
        model_source="self_reported",
        weight=38,
    ),
    _ClientProfile(
        name="codex",
        version="0.46.0",
        vendor_client=None,
        user_agent="codex_cli_rs/0.46.0",
        models=["gpt-5.6-sol", "gpt-5.2"],
        model_source="client_metadata",
        weight=26,
    ),
    _ClientProfile(
        name="cursor",
        version="1.7.0",
        vendor_client=None,
        user_agent=None,
        models=["claude-sonnet-5", "gpt-5.2"],
        model_source="self_reported",
        weight=22,
    ),
    _ClientProfile(
        name="claude-ai",
        version="0.1.0",
        vendor_client="claude-ai",
        user_agent=None,
        models=["claude-opus-5-5", "claude-sonnet-5"],
        model_source="self_reported",
        weight=9,
    ),
    _ClientProfile(
        name="visual studio code",
        version="1.105.0",
        vendor_client=None,
        user_agent=None,
        models=["gpt-5.2", "claude-sonnet-5"],
        model_source="self_reported",
        weight=5,
    ),
]

# Agents pass "unknown" when unsure, and the SDK then omits $mcp_llm_model. Codex metadata always carries it.
SELF_REPORTED_MODEL_PROBABILITY = 0.85

# Identified personas. About 70% of sessions are attached to one of these;
# the rest stay anonymous, keyed by their $session_id like the SDK does.
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

MISSING_CAPABILITY_INTENTS: list[str] = [
    "Create a new dashboard and arrange the most relevant insights on it.",
    "Update a feature flag's rollout percentage for a specific customer cohort.",
    "Create and launch an experiment for the new onboarding flow.",
    "Define a behavioral cohort of users who started but did not finish checkout.",
    "Add a deployment annotation to the signup conversion trend.",
    "Invite a teammate and grant them access to this project.",
    "Change an existing insight's filters and save the updated definition.",
    "Export a short clip from a session recording for a bug report.",
    "Resolve an error-tracking issue after confirming the fix is deployed.",
    "Configure a new data warehouse source and start its first sync.",
]


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


@frozen
class _Failure:
    error_type: str
    message: str


# The tool call and its paired $exception carry the same message, as the SDK copies it from the exception.
FAILURES: list[_Failure] = [
    _Failure(error_type="timeout", message="TimeoutError: upstream query exceeded 30s deadline"),
    _Failure(error_type="validation", message="ValidationError: missing required parameter 'project_id'"),
    _Failure(error_type="permission", message="PermissionError: API key lacks scope for this resource"),
    _Failure(error_type="internal", message="ConnectionError: ClickHouse connection reset by peer"),
    _Failure(error_type="rate_limited", message="RateLimitError: too many requests, retry after 10s"),
]

# Fraction of failing tool calls that also emit a paired $exception event.
EXCEPTION_PAIR_PROBABILITY = 0.6


@frozen
class _SeededSession:
    conversation_id: str
    session_id: str
    # None for anonymous sessions: the SDK then uses each event's $session_id as its distinct id.
    identified_distinct_id: str | None
    person_id: str | None
    person_properties: dict[str, Any]
    common_properties: dict[str, Any]
    session_end: datetime


class Command(BaseCommand):
    help = "Seed MCP analytics events into ClickHouse for local testing."

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
        parser.add_argument(
            "--missing-capabilities",
            type=int,
            default=None,
            help="Number of missing-capability events to attach to distinct seeded sessions. "
            "Defaults to 8, clamped to --sessions.",
        )
        parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducible output.")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete data previously seeded by this command before seeding — events marked with "
            "$mcp_seeded, plus the session intent rows those events belong to. Genuine MCP traffic "
            "and data seeded before the marker existed are left alone.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        session_count: int = options["sessions"]
        min_calls: int = options["min_calls"]
        max_calls: int = options["max_calls"]
        days: int = options["days"]
        # An explicit value is validated against --sessions; the default clamps instead,
        # so low-volume smoke runs (--sessions 5) work without extra flags.
        explicit_missing_capabilities: int | None = options["missing_capabilities"]
        missing_capability_count: int = (
            explicit_missing_capabilities if explicit_missing_capabilities is not None else min(8, session_count)
        )
        seed: int | None = options["seed"]
        clear: bool = options["clear"]

        if min_calls > max_calls:
            self.stderr.write(self.style.ERROR("--min-calls must be <= --max-calls"))
            return
        if missing_capability_count < 0 or missing_capability_count > session_count:
            self.stderr.write(self.style.ERROR("--missing-capabilities must be between 0 and --sessions"))
            return

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist."))
            return

        if clear:
            # Scoped to the seeded marker so genuine SDK traffic sharing these event names
            # survives. The intent rows carry no marker of their own, so recover which
            # sessions were seeded from the events before deleting them.
            seeded_predicate = (
                "team_id = %(team_id)s AND event IN %(events)s "
                f"AND JSONExtractBool(properties, '{SEEDED_MARKER_PROPERTY}')"
            )
            clear_params = {"team_id": team_id, "events": SEEDED_EVENT_NAMES}
            # Read through the distributed table: the sharded tables below only see the local shard.
            read_table, *_ = events_read_tables_via_sync_execute()
            seeded_session_ids = [
                session_id
                for (session_id,) in sync_execute(
                    f"SELECT DISTINCT JSONExtractString(properties, '$session_id') "
                    f"FROM {read_table} WHERE {seeded_predicate}",
                    clear_params,
                )
                if session_id
            ]
            # Both tables create_event dual-writes to, and only where they exist.
            for table in events_data_tables_via_sync_execute():
                sync_execute(
                    f"ALTER TABLE {table} DELETE WHERE {seeded_predicate} SETTINGS mutations_sync=1",
                    clear_params,
                )
            if seeded_session_ids:
                with team_scope(team_id):
                    MCPSession.objects.filter(team=team, session_id__in=seeded_session_ids).delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Cleared previously seeded MCP data for team {team_id} ({len(seeded_session_ids)} sessions)."
                )
            )

        rng = random.Random(seed)
        now = datetime.now(tz=UTC)
        total_events = 0
        seeded_sessions: list[_SeededSession] = []

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

        def emit(
            session: _SeededSession,
            event: str,
            timestamp: datetime,
            properties: dict[str, Any],
            handshake_session_id: str | None = None,
        ) -> None:
            nonlocal total_events
            # The conversation handle only rides tool arguments, so handshake events carry
            # the transport's session instead and no $mcp_conversation_id.
            if handshake_session_id:
                session_properties = {"$session_id": handshake_session_id}
            else:
                session_properties = {
                    "$session_id": session.session_id,
                    "$mcp_conversation_id": session.conversation_id,
                }
            distinct_id = session.identified_distinct_id or session_properties["$session_id"]
            person_id = session.person_id or str(uuidFromDistinctId(team.id, distinct_id))
            # A None value drops a session-wide property the SDK leaves off this event.
            merged = {SEEDED_MARKER_PROPERTY: True, **session.common_properties, **session_properties, **properties}
            create_event(
                event_uuid=uuid.uuid4(),
                event=event,
                team=team,
                distinct_id=distinct_id,
                timestamp=timestamp,
                person_id=uuid.UUID(person_id),
                person_properties=session.person_properties,
                person_mode="full" if session.identified_distinct_id else "propertyless",
                properties={key: value for key, value in merged.items() if value is not None},
            )
            total_events += 1

        for persona in IDENTIFIED_PERSONAS:
            ensure_person(
                persona["distinct_id"],
                {"email": persona["email"], "name": persona["name"], "role": persona["role"]},
                is_identified=True,
            )

        for session_idx in range(session_count):
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
            session_start_ms = int(session_start.timestamp() * 1000)

            # The SDK mints a uuidv7 conversation handle on the first tool call and derives
            # $session_id from it, so every call in the conversation shares one session.
            conversation_id = str(uuid7(session_start_ms, rng))
            session_id = session_id_from_conversation(conversation_id)
            is_stateless = rng.random() < STATELESS_SESSION_PROBABILITY

            common_properties: dict[str, Any] = {}
            identified_distinct_id: str | None = None
            person_uuid: str | None = None
            person_props: dict[str, Any] = {}
            if rng.random() < IDENTIFIED_PROBABILITY:
                identified_distinct_id = rng.choice(IDENTIFIED_PERSONAS)["distinct_id"]
                person_uuid, person_props = ensure_person(identified_distinct_id, {}, is_identified=True)
            else:
                # Without an identified user the SDK turns off person processing,
                # so no person row exists for these sessions.
                common_properties["$process_person_profile"] = False

            client = rng.choices(CLIENT_PROFILES, weights=[c.weight for c in CLIENT_PROFILES], k=1)[0]
            common_properties.update(
                {
                    "$lib": SDK_LIB_NAME,
                    "$mcp_source": NEW_SDK_SOURCE,
                    "$mcp_server_name": MCP_SERVER_NAME,
                    "$mcp_server_version": MCP_SERVER_VERSION,
                    "$mcp_client_name": client.name,
                    "$mcp_client_version": client.version,
                    "$mcp_protocol_version": STATELESS_PROTOCOL_VERSION if is_stateless else LEGACY_PROTOCOL_VERSION,
                }
            )
            if client.vendor_client:
                common_properties["$mcp_vendor_client"] = client.vendor_client
            if client.user_agent:
                common_properties["$mcp_client_user_agent"] = client.user_agent
            model_properties: dict[str, Any] = {}
            if client.model_source == "client_metadata" or rng.random() < SELF_REPORTED_MODEL_PROBABILITY:
                model_properties = {
                    "$mcp_llm_model": rng.choice(client.models),
                    "$mcp_llm_model_source": client.model_source,
                }

            session = _SeededSession(
                conversation_id=conversation_id,
                session_id=session_id,
                identified_distinct_id=identified_distinct_id,
                person_id=person_uuid,
                person_properties=person_props,
                common_properties=common_properties,
                session_end=session_start + total_call_duration,
            )

            listed_tools = {"$mcp_listed_tool_names": [*TOOL_NAMES, *UNCALLED_TOOL_NAMES]}
            if is_stateless:
                # No handshake. tools/list carries no conversation handle, so the SDK falls back
                # to the id the per-request server instance minted.
                emit(
                    session,
                    "$mcp_tools_list",
                    session_start - timedelta(seconds=1),
                    listed_tools,
                    handshake_session_id=f"ses_{uuid7(session_start_ms - 1000, rng)}",
                )
            else:
                token_session_id = f"ses_{uuid7(session_start_ms - 2000, rng)}"
                emit(
                    session,
                    "$mcp_initialize",
                    session_start - timedelta(seconds=2),
                    {},
                    handshake_session_id=token_session_id,
                )
                emit(
                    session,
                    "$mcp_tools_list",
                    session_start - timedelta(seconds=1),
                    listed_tools,
                    handshake_session_id=token_session_id,
                )

            # One coherent intent per session so the clustering page has themes to group.
            primary_tool = rng.choice(TOOL_NAMES)
            session_intent = rng.choice(INTENTS_BY_TOOL.get(primary_tool, [DEFAULT_INTENT]))

            cumulative_offset_s = 0
            for call_idx in range(calls):
                cumulative_offset_s += call_intervals[call_idx]
                timestamp = session_start + timedelta(seconds=cumulative_offset_s)
                tool_name = rng.choices(TOOL_NAMES, weights=list(TOOL_WEIGHTS.values()), k=1)[0]
                # Skew error rate and latency per tool so the Tool quality tab has variation.
                tool_error_rate = (stable_hash(tool_name) % 30) / 100.0
                is_error = rng.random() < tool_error_rate
                base_latency = 80 + (stable_hash(tool_name) % 400)
                duration_ms = max(1, int(rng.gauss(base_latency, base_latency * 0.4)))
                tool_properties: dict[str, Any] = {
                    **model_properties,
                    "$mcp_resource_name": tool_name,
                    "$mcp_tool_name": tool_name,
                    "$mcp_tool_category": TOOL_CATEGORIES.get(tool_name, "Other"),
                    "$mcp_tool_description": TOOL_DESCRIPTIONS.get(tool_name, ""),
                    "$mcp_intent": session_intent,
                    "$mcp_intent_source": rng.choices(["context_parameter", "inferred"], weights=[7, 3], k=1)[0],
                    "$mcp_is_error": is_error,
                }
                failure = rng.choice(FAILURES) if is_error else None
                if failure:
                    duration_ms = int(duration_ms * rng.uniform(1.5, 3.0))
                    tool_properties["$mcp_error_type"] = failure.error_type
                    tool_properties["$mcp_error_message"] = failure.message
                tool_properties["$mcp_duration_ms"] = duration_ms
                emit(session, "$mcp_tool_call", timestamp, tool_properties)

                # Pair some failures with an $exception event so the tool detail
                # "Failures" table (which reads $exception events) has data.
                if failure and rng.random() < EXCEPTION_PAIR_PROBABILITY:
                    emit(
                        session,
                        "$exception",
                        timestamp,
                        {
                            "$mcp_source": None,
                            "$mcp_resource_name": tool_name,
                            "$mcp_tool_name": tool_name,
                            "$exception_types": ["MCPToolError"],
                            "$exception_values": [failure.message],
                            "$exception_list": [
                                {
                                    "type": "MCPToolError",
                                    "value": failure.message,
                                    "mechanism": {"handled": True},
                                }
                            ],
                        },
                    )

            # The session listing derives sessions on the fly from the events above,
            # but intent clustering reads MCPSession.intent (keyed by $session_id), so
            # store one row per session to give the clustering page something to group.
            with team_scope(team_id):
                MCPSession.objects.update_or_create(
                    team=team, session_id=session_id, defaults={"intent": session_intent}
                )
            seeded_sessions.append(session)
            self.stdout.write(
                f"  session {session_idx + 1}/{session_count}: {calls} tool calls (session_id={session_id})"
            )

        for session in rng.sample(seeded_sessions, k=missing_capability_count):
            emit(
                session,
                "$mcp_missing_capability",
                session.session_end + timedelta(seconds=rng.randint(1, 30)),
                {
                    "$mcp_resource_name": MISSING_CAPABILITY_TOOL_NAME,
                    "$mcp_intent": rng.choice(MISSING_CAPABILITY_INTENTS),
                    "$mcp_intent_source": "context_parameter",
                    "$mcp_is_error": False,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {session_count} sessions ({total_events} events, including "
                f"{missing_capability_count} missing-capability reports) for team {team_id}."
            )
        )
