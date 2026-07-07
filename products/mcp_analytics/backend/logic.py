import hashlib
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import QuerySet
from django.utils import timezone

from posthog.schema import DateRange

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.person import Person
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.utils import generate_cache_key

from products.mcp_analytics.backend import intent_generation
from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot, MCPSession

# How long a snapshot may sit in COMPUTING before we assume the task died and
# auto-recover. Generous because a real recompute completes in well under a
# minute even at the top_n=500 cap; anything past 10 minutes is a dead task.
STALE_COMPUTING_THRESHOLD = timedelta(minutes=10)

_MCP_TOOL_CALLS_SQL = """
SELECT
    uuid AS event_id,
    timestamp,
    toString(properties.$mcp_tool_name) AS tool_name,
    toString(properties.$mcp_intent) AS intent,
    toString(properties.$mcp_is_error) AS is_error_raw,
    toString(properties.$mcp_error_message) AS error_message,
    toString(properties.$mcp_duration_ms) AS duration_ms_raw
FROM events
WHERE event = {event}
    AND timestamp >= {date_from}
    AND $session_id = {session_id}
ORDER BY timestamp ASC, event_id ASC
LIMIT {limit}
OFFSET {offset}
"""


def list_submissions(team: Team, kind: enums.SubmissionKind) -> QuerySet[MCPAnalyticsSubmission]:
    return MCPAnalyticsSubmission.objects.filter(team=team, kind=kind).order_by("-created_at")


SESSION_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "session_id",
        "session_start",
        "session_end",
        "duration_seconds",
        "tool_call_count",
        "mcp_client_name",
        "distinct_id",
    }
)
DEFAULT_SESSION_SORT_COLUMN = "session_start"

# Default window when the caller doesn't pass a date range. Matches the dashboard
# default so both tabs show the same set of sessions out of the box. The UI always
# sends an explicit range; this only covers param-less API/token callers.
DEFAULT_SESSIONS_DATE_FROM = "-7d"

# A session that overlaps the window must be reported with its *full* stats (true
# session_start/end/duration/tool count), not just its in-window slice. We get that
# by scanning a window padded by this buffer on each side, then keeping only sessions
# with at least one event actually inside the window. The buffer bounds the extra scan
# while capturing the whole span of any realistically-long MCP session; a session whose
# span exceeds it would have its stats clipped at the buffer edge (rare — agent
# sessions are minutes-to-hours; a multi-day span usually means a reused session_id).
SESSION_OVERLAP_BUFFER = timedelta(days=1)

# Short TTL so concurrent dashboard tabs / auto-refreshes share one ClickHouse
# aggregation instead of each re-running it — long enough to absorb a burst,
# short enough that "Reload" still feels live.
SESSIONS_CACHE_TTL_SECONDS = 30

# One row per $session_id, aggregated straight from events. The column shape
# (min/max/count/groupUniqArray/argMax) maps 1:1 onto a future AggregatingMergeTree
# if per-team volume ever warrants materialising it. __SEARCH__ / __ORDER__ are
# validated structural fragments injected before parsing; {placeholders} are HogQL
# value placeholders.
#
# Session-level windowing: aggregate over the buffered range [scan_from, scan_to] so
# each session's stats span its *whole* set of events, then keep only sessions with an
# event inside the requested [window_from, window_to] via the HAVING countIf. This is
# why a session straddling the window boundary reports full (not clipped) start/end/
# duration/count, and why its detail view (bounded by session_start) shows every event.
#
# NB: the session id reads from the `$session_id` field, NOT `properties.$session_id`.
# `$session_id` is a materialised events column; the `properties.` accessor renders it
# null-wrapped in SELECT but the raw column in HAVING/ORDER, so the search HAVING would
# mismatch the GROUP BY key and ClickHouse rejects it. The bare field renders the raw
# column consistently across SELECT/GROUP/HAVING/ORDER.
_MCP_SESSIONS_SQL = """
SELECT
    $session_id AS session_id,
    min(timestamp) AS session_start,
    max(timestamp) AS session_end,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    count() AS tool_call_count,
    groupUniqArray(properties.$mcp_tool_name) AS tools_used,
    argMax(distinct_id, timestamp) AS distinct_id,
    argMax(properties.$mcp_client_name, timestamp) AS mcp_client_name
FROM events
WHERE event = {event}
    -- Buffered range so an overlapping session's events outside the window still
    -- aggregate into its full stats; the timestamp bounds keep the sort key pruning.
    AND timestamp >= {scan_from}
    AND timestamp <= {scan_to}
    -- $session_id is a materialised String column — '' (not NULL) for sessionless
    -- events — so a bare `!= ''` drops them without a coalesce.
    AND $session_id != ''
GROUP BY session_id
-- Session-level inclusion: at least one event inside the requested window.
HAVING countIf(timestamp >= {window_from} AND timestamp <= {window_to}) > 0
    __SEARCH__
ORDER BY __ORDER__
LIMIT {limit}
OFFSET {offset}
"""

# Search is post-aggregation (folded into HAVING) so a match returns the whole session,
# not just the matching events. tools_used / distinct_id / mcp_client_name are aggregates,
# so they can only be filtered after GROUP BY.
_SESSION_SEARCH_FILTER = (
    "AND (session_id ILIKE {search} "
    "OR distinct_id ILIKE {search} "
    "OR mcp_client_name ILIKE {search} "
    "OR arrayExists(t -> t ILIKE {search}, tools_used))"
)


def _normalise_order_by(order_by: str) -> tuple[str, bool]:
    """Validate the order_by query param into ``(column, descending)``.

    Accepts a single column with an optional leading '-' for descending. Falls
    back to the default if the field isn't whitelisted; we never ORDER BY an
    arbitrary client-supplied column.
    """
    raw = (order_by or "").strip()
    if not raw:
        return DEFAULT_SESSION_SORT_COLUMN, True
    descending = raw.startswith("-")
    field = raw.lstrip("-")
    if field not in SESSION_SORT_FIELDS:
        return DEFAULT_SESSION_SORT_COLUMN, True
    return field, descending


def _sessions_cache_key(
    team_id: int, limit: int, offset: int, search: str, order_by: str, date_from: str, date_to: str
) -> str:
    payload = f"mcp_sessions_{date_from}_{date_to}_{limit}_{offset}_{search}_{order_by}"
    return generate_cache_key(team_id, payload)


def list_mcp_sessions(
    team: Team,
    limit: int,
    offset: int,
    search: str = "",
    order_by: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
) -> contracts.MCPSessionsPage:
    """List a page of MCP sessions for a team, aggregated on the fly from $mcp_tool_call events.

    One row per $session_id whose session overlaps the selected window, grouped in ClickHouse and
    scoped to the team so the events sort key prunes the scan. Stats are full-session: a session
    that straddles the window boundary reports its true start/end/duration/tool count, not just the
    in-window slice (see ``_MCP_SESSIONS_SQL`` for the buffered-scan + ``countIf`` mechanism).
    Over-fetches one row to report ``has_next`` (replay-style) without a separate count query.
    Results are cached briefly so concurrent dashboard refreshes share a single aggregation.

    ``date_from`` / ``date_to`` accept PostHog date strings (relative like ``-7d`` or absolute
    ISO timestamps), resolved via ``QueryDateRange`` like the dashboard. ``date_from`` defaults to
    ``DEFAULT_SESSIONS_DATE_FROM`` when omitted.

    ``search`` does case-insensitive substring matching across session_id,
    distinct_id, mcp_client_name, and any element of tools_used. ``order_by`` is a
    whitelisted column name; prefix with '-' for descending.

    Person email/name are resolved from distinct_id via personhog. ``intent`` is
    empty until the ad-hoc summary endpoint (separate PR) fills the intent seam.
    """
    effective_date_from = date_from or DEFAULT_SESSIONS_DATE_FROM
    cache_key = _sessions_cache_key(team.id, limit, offset, search, order_by, effective_date_from, date_to or "")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    page = _query_mcp_sessions(
        team,
        limit=limit,
        offset=offset,
        search=search,
        order_by=order_by,
        date_from=effective_date_from,
        date_to=date_to,
    )
    # Don't cache empty results: a newly set-up team's first sessions would
    # otherwise stay hidden for the full TTL.
    if page.results:
        cache.set(cache_key, page, SESSIONS_CACHE_TTL_SECONDS)
    return page


def _query_mcp_sessions(
    team: Team,
    limit: int,
    offset: int,
    search: str,
    order_by: str,
    date_from: str,
    date_to: str | None,
) -> contracts.MCPSessionsPage:
    column, descending = _normalise_order_by(order_by)
    # Append the unique session_id as a tiebreaker so the sort is a *total* order.
    # Without it, ties on the sort column (e.g. equal session_end) make offset
    # pagination drop or repeat rows across pages.
    direction = "DESC" if descending else "ASC"
    order_text = f"{column} {direction}" if column == "session_id" else f"{column} {direction}, session_id ASC"

    # Resolve the date strings (relative like '-7d' or absolute ISO) to concrete bounds,
    # the same path the dashboard uses. We need both the window and a buffered scan range,
    # so resolve here rather than via the HogQL {filters} placeholder (which only yields one).
    query_date_range = QueryDateRange(
        date_range=DateRange(date_from=date_from, date_to=date_to),
        team=team,
        interval=None,
        now=timezone.now(),
    )
    window_from = query_date_range.date_from()
    window_to = query_date_range.date_to()

    # Over-fetch one row to learn whether a next page exists, without a count query.
    placeholders: dict[str, ast.Expr] = {
        "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
        "scan_from": ast.Constant(value=window_from - SESSION_OVERLAP_BUFFER),
        "scan_to": ast.Constant(value=window_to + SESSION_OVERLAP_BUFFER),
        "window_from": ast.Constant(value=window_from),
        "window_to": ast.Constant(value=window_to),
        "limit": ast.Constant(value=limit + 1),
        "offset": ast.Constant(value=offset),
    }

    search_text = ""
    term = search.strip()
    if term:
        search_text = _SESSION_SEARCH_FILTER
        placeholders["search"] = ast.Constant(value=f"%{term}%")

    sql = _MCP_SESSIONS_SQL.replace("__SEARCH__", search_text).replace("__ORDER__", order_text)
    query = parse_select(sql, placeholders=placeholders)

    # name matches the endpoint operation_id so the query is traceable in query_log
    # (JSONExtractString(log_comment, 'name') = 'mcp_analytics_sessions_list').
    with tags_context(
        product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name="mcp_analytics_sessions_list"
    ):
        response = execute_hogql_query(query=query, team=team)

    rows = [_row_to_session_dict(row) for row in (response.results or [])]
    has_next = len(rows) > limit
    rows = rows[:limit]
    persons_by_distinct_id = _resolve_persons(team.id, [row["distinct_id"] for row in rows])
    intents_by_session = _attach_intents(team, [row["session_id"] for row in rows])
    results = [_to_session_contract(row, persons_by_distinct_id, intents_by_session) for row in rows]
    return contracts.MCPSessionsPage(results=results, has_next=has_next)


def _row_to_session_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "session_id": row[0] or "",
        "session_start": row[1],
        "session_end": row[2],
        "duration_seconds": max(0, int(row[3] or 0)),
        "tool_call_count": int(row[4] or 0),
        "tools_used": [tool for tool in (row[5] or []) if tool],
        "distinct_id": row[6] or "",
        "mcp_client_name": row[7] or "",
    }


def _attach_intents(team: Team, session_ids: list[str]) -> dict[str, str]:
    """Look up persisted session intents keyed by session_id.

    A single indexed read over the page's session_ids against MCPSession; sessions
    whose intent hasn't been generated yet are simply absent. Intents are produced
    on demand via ``generate_session_intent``.
    """
    if not session_ids:
        return {}
    rows = MCPSession.objects.filter(team=team, session_id__in=session_ids).values_list("session_id", "intent")
    return {session_id: intent for session_id, intent in rows if intent}


def generate_session_intent(team: Team, session_id: str, date_from: datetime | None = None) -> str:
    """Return the session's intent summary, generating and persisting it on first request.

    Cache-on-empty: an existing non-empty ``MCPSession.intent`` is returned as-is. Otherwise the
    session's recorded ``$mcp_intent``s are summarised by an LLM and persisted (one row per
    ``(team, session_id)``). A session with no recorded intents returns ``NO_INTENT_MESSAGE``
    without an LLM call and without persisting anything, so it stays retryable and the listing
    doesn't surface a non-intent as an intent.
    Raises ``contracts.IntentGenerationUnavailable`` if the LLM is unreachable.

    ``date_from`` bounds the event scan; the UI passes the session's start (the same bound
    ``list_mcp_tool_calls`` uses) so any listed session stays summarisable.
    """
    existing = MCPSession.objects.filter(team=team, session_id=session_id).values_list("intent", flat=True).first()
    if existing:
        return existing

    intents = intent_generation.fetch_session_intents(team, session_id, date_from=date_from)
    if not intents:
        return intent_generation.NO_INTENT_MESSAGE

    summary = intent_generation.summarize_intents(intents, team)
    MCPSession.objects.update_or_create(team=team, session_id=session_id, defaults={"intent": summary})
    return summary


INTENT_DIGEST_CACHE_TTL = 60 * 60


def generate_intent_digest(team: Team) -> contracts.IntentDigest:
    """Return a project-level LLM digest of what agents are trying to do, for the activity tab.

    Structured output: a one-sentence summary plus 2-5 semantic themes (name, description,
    count, verbatim example, tools). Content-addressed cache: keyed by the current intent
    corpus, so it only regenerates when new intents arrive (and at most refreshes hourly via
    the TTL). A project with no recorded intents returns a null digest without an LLM call.
    Raises ``contracts.IntentGenerationUnavailable`` if the LLM is unreachable.
    """
    intents = intent_generation.fetch_recent_project_intents(team)
    if not intents:
        return contracts.IntentDigest(digest=None, intent_count=0, themes=[])

    corpus_hash = hashlib.sha256("\n".join(intent for intent, _ in intents).encode()).hexdigest()
    cache_key = generate_cache_key(team.pk, f"mcp_intent_digest_v2/{corpus_hash}")
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return contracts.IntentDigest(
            digest=cached.get("summary"),
            intent_count=len(intents),
            themes=[contracts.IntentTheme(**theme) for theme in cached.get("themes", [])],
        )

    parsed = intent_generation.summarize_project_intents(intents, team)
    themes = [
        contracts.IntentTheme(
            name=theme.name,
            description=theme.description,
            intent_count=theme.intent_count,
            example_intent=theme.example_intent,
            tools=theme.tools,
        )
        for theme in parsed.themes
    ]
    cache.set(
        cache_key,
        {"summary": parsed.summary, "themes": [vars(theme) | {"tools": list(theme.tools)} for theme in themes]},
        INTENT_DIGEST_CACHE_TTL,
    )
    return contracts.IntentDigest(digest=parsed.summary, intent_count=len(intents), themes=themes)


def _resolve_persons(team_id: int, distinct_ids: list[str]) -> dict[str, Person]:
    unique_ids = list({distinct_id for distinct_id in distinct_ids if distinct_id})
    if not unique_ids:
        return {}
    with personhog_caller_tag("mcp-analytics/persons"):
        return get_persons_mapped_by_distinct_id(team_id, unique_ids)


def _person_display(person: Person | None) -> dict[str, str]:
    if person is None:
        return {"email": "", "name": ""}
    props = person.properties or {}
    return {
        "email": str(props.get("email") or ""),
        "name": str(props.get("name") or ""),
    }


def _to_session_contract(
    row: dict[str, Any],
    persons_by_distinct_id: dict[str, Person],
    intents_by_session: dict[str, str],
) -> contracts.MCPSession:
    person_display = _person_display(persons_by_distinct_id.get(row["distinct_id"]))
    return contracts.MCPSession(
        session_id=row["session_id"],
        tool_calls=row["tool_call_count"],
        session_start=row["session_start"],
        session_end=row["session_end"],
        distinct_id_count=0,
        tools_used=row["tools_used"],
        mcp_client_name=row["mcp_client_name"],
        distinct_id=row["distinct_id"],
        person_email=person_display["email"],
        person_name=person_display["name"],
        intent=intents_by_session.get(row["session_id"], ""),
    )


def list_mcp_tool_calls(
    team: Team,
    session_id: str,
    limit: int,
    offset: int,
    date_from: datetime | None = None,
) -> contracts.MCPToolCallsPage:
    """List a page of a session's $mcp_tool_call events in chronological order.

    ``date_from`` is the timestamp lower bound that lets the events sort key prune the scan
    (``$session_id`` alone isn't in the sort key). The caller passes the session's start so the
    detail view stays correct for sessions older than the default ``SESSION_EVENTS_LOOKBACK``;
    when omitted it falls back to that window for param-less API/token callers.

    ``limit`` / ``offset`` page through the session's calls; over-fetch one row to report
    ``has_next`` without a separate count query.
    """
    query = parse_select(
        _MCP_TOOL_CALLS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "date_from": ast.Constant(value=date_from or (timezone.now() - intent_generation.SESSION_EVENTS_LOOKBACK)),
            "session_id": ast.Constant(value=session_id),
            "limit": ast.Constant(value=limit + 1),
            "offset": ast.Constant(value=offset),
        },
    )
    with tags_context(
        product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name="mcp_analytics_sessions_tool_calls"
    ):
        response = execute_hogql_query(query=query, team=team)
    rows = response.results or []
    has_next = len(rows) > limit
    results = [
        contracts.MCPToolCall(
            event_id=str(row[0]) if row[0] else "",
            timestamp=row[1],
            tool_name=row[2] or "",
            intent=row[3] or "",
            is_error=str(row[4]).lower() in ("true", "1"),
            error_message=row[5] or "",
            duration_ms=_parse_int(row[6]),
        )
        for row in rows[:limit]
    ]
    return contracts.MCPToolCallsPage(results=results, has_next=has_next)


def _parse_int(value: str | int | None) -> int | None:
    if value is None or value == "" or value == "null":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_intent_cluster_snapshot(team: Team) -> contracts.IntentClusterSnapshot:
    """Return the current intent cluster snapshot for a team.

    When no snapshot exists yet, returns an empty IDLE one so callers can
    render the "compute" CTA without distinguishing "missing" from "empty".

    Defensive side effect: any row stuck in COMPUTING past
    STALE_COMPUTING_THRESHOLD is auto-flipped to ERROR so the UI can offer
    a retry. The Celery task may have died between writing COMPUTING and
    writing its final status (worker restart, OOM, etc.) and otherwise has
    no path back to a usable state.
    """
    MCPIntentClusterSnapshot.objects.filter(
        team=team,
        status=MCPIntentClusterSnapshot.Status.COMPUTING,
        updated_at__lt=timezone.now() - STALE_COMPUTING_THRESHOLD,
    ).update(
        status=MCPIntentClusterSnapshot.Status.ERROR,
        error_message="Recompute task did not complete within the expected window. Retry to try again.",
    )

    snapshot = MCPIntentClusterSnapshot.objects.filter(team=team).select_related("last_computed_by").first()
    if snapshot is None:
        return contracts.IntentClusterSnapshot(
            status=MCPIntentClusterSnapshot.Status.IDLE,
            error_message="",
            last_computed_at=None,
            last_computed_by_email="",
            clusters=[],
            computed_with=None,
        )

    blob = snapshot.clusters or {}
    clusters_raw = blob.get("clusters", []) if isinstance(blob, dict) else []
    meta_raw = blob.get("computed_with") if isinstance(blob, dict) else None

    return contracts.IntentClusterSnapshot(
        status=snapshot.status,
        error_message=snapshot.error_message,
        last_computed_at=snapshot.last_computed_at,
        last_computed_by_email=snapshot.last_computed_by.email if snapshot.last_computed_by else "",
        clusters=[_to_cluster_dto(item) for item in clusters_raw if isinstance(item, dict)],
        computed_with=_to_meta_dto(meta_raw) if isinstance(meta_raw, dict) else None,
    )


def _to_cluster_dto(item: dict[str, Any]) -> contracts.IntentCluster:
    journey_raw = item.get("journey")
    return contracts.IntentCluster(
        id=int(item.get("id", 0)),
        label=str(item.get("label", "")),
        intent_count=int(item.get("intent_count", 0)),
        session_count=int(item.get("session_count", 0)),
        call_count=int(item.get("call_count", 0)),
        error_count=int(item.get("error_count", 0)),
        error_rate_pct=float(item.get("error_rate_pct", 0.0)),
        routing_entropy=float(item.get("routing_entropy", 0.0)),
        tool_distribution=[
            contracts.IntentClusterToolEntry(
                tool=str(entry.get("tool", "")),
                count=int(entry.get("count", 0)),
                pct=float(entry.get("pct", 0.0)),
                errors=int(entry.get("errors", 0)),
                error_rate_pct=float(entry.get("error_rate_pct", 0.0)),
            )
            for entry in item.get("tool_distribution", [])
            if isinstance(entry, dict)
        ],
        sample_intents=[str(s) for s in item.get("sample_intents", []) if isinstance(s, str)],
        journey=_to_journey_dto(journey_raw) if isinstance(journey_raw, dict) else None,
    )


def _to_journey_path_dto(path: dict[str, Any]) -> contracts.IntentClusterJourneyPath:
    return contracts.IntentClusterJourneyPath(
        steps=[str(s) if s is not None else None for s in path.get("steps", [])],
        outcome=str(path.get("outcome", "completed")),
        count=int(path.get("count", 0)),
    )


def _to_journey_dto(journey: dict[str, Any]) -> contracts.IntentClusterJourney:
    return contracts.IntentClusterJourney(
        paths=[_to_journey_path_dto(p) for p in journey.get("paths", []) if isinstance(p, dict)],
        total_sessions=int(journey.get("total_sessions", 0)),
        leak=(_to_journey_path_dto(journey["leak"]) if isinstance(journey.get("leak"), dict) else None),
    )


def _to_meta_dto(meta: dict[str, Any]) -> contracts.IntentClusterSnapshotMeta:
    return contracts.IntentClusterSnapshotMeta(
        distance_threshold=float(meta.get("distance_threshold", 0.0)),
        embedding_model=str(meta.get("embedding_model", "")),
        n_intents=int(meta.get("n_intents", 0)),
        n_clusters=int(meta.get("n_clusters", 0)),
    )


def create_feedback_submission(
    team: Team, created_by: User | None, submission: contracts.CreateFeedbackSubmission
) -> MCPAnalyticsSubmission:
    return MCPAnalyticsSubmission.objects.create(
        team=team,
        created_by=created_by,
        kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
        goal=submission.goal,
        summary=submission.feedback,
        category=submission.category,
        attempted_tool=submission.context.attempted_tool,
        mcp_client_name=submission.context.mcp_client_name,
        mcp_client_version=submission.context.mcp_client_version,
        mcp_protocol_version=submission.context.mcp_protocol_version,
        mcp_transport=submission.context.mcp_transport,
        mcp_session_id=submission.context.mcp_session_id,
        mcp_trace_id=submission.context.mcp_trace_id,
    )


def create_missing_capability_submission(
    team: Team, created_by: User | None, submission: contracts.CreateMissingCapabilitySubmission
) -> MCPAnalyticsSubmission:
    return MCPAnalyticsSubmission.objects.create(
        team=team,
        created_by=created_by,
        kind=MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY,
        goal=submission.goal,
        summary=submission.missing_capability,
        blocked=submission.blocked,
        attempted_tool=submission.context.attempted_tool,
        mcp_client_name=submission.context.mcp_client_name,
        mcp_client_version=submission.context.mcp_client_version,
        mcp_protocol_version=submission.context.mcp_protocol_version,
        mcp_transport=submission.context.mcp_transport,
        mcp_session_id=submission.context.mcp_session_id,
        mcp_trace_id=submission.context.mcp_trace_id,
    )
