import json
import hashlib
import dataclasses
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

from products.mcp_analytics.backend import intent_generation, mcp_harness
from products.mcp_analytics.backend.constants import (
    MAX_SNAPSHOT_CLUSTERS,
    MCP_MISSING_CAPABILITY_EVENT,
    MCP_TOOL_CALL_EVENT,
)
from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot, MCPSession

# How long a snapshot may sit in COMPUTING before we assume the run died and
# auto-recover. Must exceed the compute activity's schedule_to_close budget
# (400s, covering queue wait + both attempts — see intent_clustering
# constants); past that, nothing can still legitimately write a final status,
# so the row is a dead run whose worker never reached _mark_error.
STALE_COMPUTING_THRESHOLD = timedelta(minutes=8)

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
# Floor on how often a project can trigger a fresh generation. The corpus hash alone cannot bound
# this: a busy server cycles its hundred most recent intents in well under a minute, so every
# dashboard refresh would miss the content-addressed key and call the LLM again. Serving the
# previous digest for a few minutes costs nothing: the card answers "what are agents working on
# lately", not "what happened in the last thirty seconds".
INTENT_DIGEST_MIN_REGENERATE_SECONDS = 10 * 60


def _cached_digest(cached: object) -> contracts.IntentDigest | None:
    """Rehydrate a cached digest, or None when the payload is absent or predates the current shape.

    Returning None sends the caller back to the LLM rather than raising, so a shape change that
    outlives its cache key degrades into one extra generation instead of a 500.
    """
    if not isinstance(cached, dict) or not isinstance(cached.get("themes"), list):
        return None
    try:
        themes = [contracts.IntentTheme(**theme) for theme in cached["themes"]]
    except TypeError:
        return None
    # Frozen dataclasses don't validate, so a payload with the right keys and wrong value types
    # would construct here and only fail later in the serializer, past the 503 handler.
    if any(not isinstance(theme.intent_count, int) or not isinstance(theme.tools, list) for theme in themes):
        return None
    return contracts.IntentDigest(
        digest=cached.get("summary"), intent_count=cached.get("intent_count", 0), themes=themes
    )


def generate_intent_digest(team: Team) -> contracts.IntentDigest:
    """Return a project-level LLM digest of what agents are trying to do, for the activity tab.

    A one-sentence summary plus up to five semantic themes. The LLM only groups the intents and
    names each group; counts, tools, and the verbatim example are resolved from the corpus by
    ``intent_generation.resolve_themes``, so nothing countable on the card is model-generated.

    Two cache layers, because the two ends of the volume range want opposite things. The
    content-addressed key means a quiet project never pays for a regeneration while its intents sit
    unchanged. The recency key bounds a busy project, whose corpus is different on every request, to
    one generation per ``INTENT_DIGEST_MIN_REGENERATE_SECONDS``. ``intent_count`` travels in the
    payload so a served digest always reports the corpus it was actually derived from, keeping the
    theme shares consistent with the total the card displays.

    A project with no recorded intents returns a null digest without an LLM call. Raises
    ``contracts.IntentGenerationUnavailable`` if the LLM is unreachable.
    """
    intents = intent_generation.fetch_recent_project_intents(team)
    if not intents:
        return contracts.IntentDigest(digest=None, intent_count=0)

    corpus_hash = hashlib.sha256("\x00".join(f"{intent}\x01{tool}" for intent, tool in intents).encode()).hexdigest()
    corpus_key = generate_cache_key(team.pk, f"mcp_intent_digest_v3/{corpus_hash}")
    recent_key = generate_cache_key(team.pk, "mcp_intent_digest_v3/recent")
    for key in (corpus_key, recent_key):
        cached = _cached_digest(cache.get(key))
        if cached is not None:
            return cached

    parsed = intent_generation.summarize_project_intents(intents, team)
    themes = intent_generation.resolve_themes(parsed, intents)
    payload = {
        "summary": parsed.summary,
        "intent_count": len(intents),
        "themes": [dataclasses.asdict(theme) for theme in themes],
    }
    cache.set(corpus_key, payload, INTENT_DIGEST_CACHE_TTL)
    cache.set(recent_key, payload, INTENT_DIGEST_MIN_REGENERATE_SECONDS)
    return contracts.IntentDigest(digest=parsed.summary, intent_count=len(intents), themes=themes)


# The activity queries read `properties.*`, which decompresses the properties column for
# every matching row, and the view is reachable at any project volume. 30 days is
# effectively all-time for the low-volume servers the activity stage exists for, and a
# hard cap on the scan for high-volume projects that open the tab.
ACTIVITY_WINDOW = timedelta(days=30)
ACTIVITY_TOP_TOOLS_LIMIT = 5
ACTIVITY_CLIENTS_LIMIT = 6
ACTIVITY_RECENT_CALLS_LIMIT = 20

_ACTIVITY_STATS_SQL = f"""
SELECT
    countIf(is_tool_call) AS total_calls,
    uniqIf(tool, is_tool_call) AS distinct_tools,
    uniqIf(session_id, is_tool_call AND session_id != '') AS distinct_sessions,
    -- Counted over the resolved *label*, not the token: one client can arrive under
    -- several tokens (`codex-mcp-client` and the `openai-mcp … (Codex)` user-agent both
    -- mean Codex), which the Clients card folds into one row, so counting tokens would
    -- put "2 clients" next to a one-row card. The raw `$mcp_client_name` is absent from
    -- every non-initialize call and cannot be counted here at all.
    uniqIf({mcp_harness.harness_label_or_token_sql("h")}, is_tool_call AND h != '') AS distinct_clients,
    countIf(is_tool_call AND has_intent) AS calls_with_intent,
    countIf(is_tool_call AND is_error) AS error_calls,
    countIf(is_missing_capability) AS missing_capability_reports
FROM (
    SELECT
        event = {{tool_call_event}} AS is_tool_call,
        event = {{missing_capability_event}} AS is_missing_capability,
        properties.$mcp_tool_name AS tool,
        $session_id AS session_id,
        coalesce(properties.$mcp_intent, '') != '' AS has_intent,
        toString(properties.$mcp_is_error) IN ('true', '1') AS is_error,
        {mcp_harness.HARNESS_TOKEN_SQL} AS h,
        {mcp_harness.HARNESS_DISPLAY_NAME_SQL} AS client_display
    FROM events
    WHERE event IN ({{tool_call_event}}, {{missing_capability_event}}) AND timestamp >= {{date_from}}
)
"""

_ACTIVITY_TOP_TOOLS_SQL = """
SELECT
    properties.$mcp_tool_name AS tool,
    count() AS calls,
    countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors
FROM events
WHERE event = {tool_call_event} AND properties.$mcp_tool_name IS NOT NULL AND timestamp >= {date_from}
GROUP BY tool
ORDER BY calls DESC
LIMIT {limit}
"""

# Resolved through the canonical classifier rather than the raw `$mcp_client_name`,
# which is absent on any call that isn't the session's `initialize` — reading it alone
# left the large majority of calls unattributed and lumped whole clients under one
# "unknown" row. `HARNESS_TOKEN_SQL` falls back through the other identity signals the
# same event already carries, and the label bucketing folds one client's variant spellings
# (differing case, or a name carrying mcp-remote's proxy signature) into a single row.
# Unrecognized clients are named verbatim: this is a ranked top-N list, so a
# self-reported name is more use than collapsing it into "Other".
_ACTIVITY_CLIENTS_SQL = f"""
SELECT
    {mcp_harness.harness_label_or_token_sql("h")} AS client,
    count() AS calls
FROM (
    SELECT
        {mcp_harness.HARNESS_TOKEN_SQL} AS h,
        {mcp_harness.HARNESS_DISPLAY_NAME_SQL} AS client_display
    FROM events
    WHERE event = {{tool_call_event}} AND timestamp >= {{date_from}}
)
GROUP BY client
ORDER BY calls DESC
LIMIT {{limit}}
"""

_ACTIVITY_RECENT_CALLS_SQL = f"""
SELECT
    timestamp,
    tool,
    intent,
    is_error,
    error_raw,
    duration_ms,
    -- Resolved, not raw: the live feed showed a blank caller on most rows otherwise.
    {mcp_harness.harness_label_or_token_sql("h")} AS client_name
FROM (
    SELECT
        timestamp,
        properties.$mcp_tool_name AS tool,
        properties.$mcp_intent AS intent,
        toString(properties.$mcp_is_error) IN ('true', '1') AS is_error,
        if(toString(properties.$mcp_is_error) IN ('true', '1'),
           coalesce(nullIf(toString(properties.$mcp_error_message), ''), toString(properties.$mcp_response)),
           NULL) AS error_raw,
        toFloat(properties.$mcp_duration_ms) AS duration_ms,
        {mcp_harness.HARNESS_TOKEN_SQL} AS h,
        {mcp_harness.HARNESS_DISPLAY_NAME_SQL} AS client_display
    FROM events
    WHERE event = {{tool_call_event}} AND timestamp >= {{date_from}}
    ORDER BY timestamp DESC
    LIMIT {{limit}}
)
ORDER BY timestamp DESC
"""


def _extract_error_message(raw: Any) -> str | None:
    """Pull the human-readable text out of a failed call's error payload.

    ``$mcp_error_message`` is used verbatim when the SDK set it; otherwise ``$mcp_response``
    is an MCP content envelope ({"content": [{"type": "text", "text": ...}]}) to unwrap.
    """
    value = str(raw).strip() if raw is not None else ""
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        # HogQL's property accessor strips a string value's outer quotes but keeps the
        # inner escapes; re-wrap to unescape, then parse the payload it encodes.
        try:
            parsed = json.loads(json.loads(f'"{value}"'))
        except (json.JSONDecodeError, ValueError):
            return value
    if isinstance(parsed, dict):
        content = parsed.get("content")
        if isinstance(content, list):
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text" and isinstance(chunk.get("text"), str):
                    return chunk["text"] or None
        message = parsed.get("message")
        if isinstance(message, str) and message:
            return message
    return value


def _run_activity_query(team: Team, sql: str, name: str, placeholders: dict[str, ast.Constant]) -> list[Any]:
    query = parse_select(sql, placeholders={**placeholders})
    with tags_context(product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name=name):
        response = execute_hogql_query(query=query, team=team)
    return response.results or []


def get_activity_overview(team: Team) -> contracts.ActivityOverview:
    """Compute everything the activity view renders, bounded to ``ACTIVITY_WINDOW``.

    Always computed fresh: the view's whole point is watching data arrive, so callers
    poll this endpoint rather than a stale cache.
    """
    date_from = ast.Constant(value=timezone.now() - ACTIVITY_WINDOW)
    tool_call_event = ast.Constant(value=MCP_TOOL_CALL_EVENT)

    stats_rows = _run_activity_query(
        team,
        _ACTIVITY_STATS_SQL,
        "mcp_analytics_activity_stats",
        {
            "tool_call_event": tool_call_event,
            "missing_capability_event": ast.Constant(value=MCP_MISSING_CAPABILITY_EVENT),
            "date_from": date_from,
        },
    )
    stats_row = stats_rows[0] if stats_rows else [0] * 7
    stats = contracts.ActivityStats(
        total_calls=_parse_int(stats_row[0]) or 0,
        distinct_tools=_parse_int(stats_row[1]) or 0,
        distinct_sessions=_parse_int(stats_row[2]) or 0,
        distinct_clients=_parse_int(stats_row[3]) or 0,
        calls_with_intent=_parse_int(stats_row[4]) or 0,
        error_calls=_parse_int(stats_row[5]) or 0,
        missing_capability_reports=_parse_int(stats_row[6]) or 0,
    )

    top_tools = [
        contracts.ActivityToolRow(tool=str(row[0] or ""), calls=_parse_int(row[1]) or 0, errors=_parse_int(row[2]) or 0)
        for row in _run_activity_query(
            team,
            _ACTIVITY_TOP_TOOLS_SQL,
            "mcp_analytics_activity_top_tools",
            {
                "tool_call_event": tool_call_event,
                "date_from": date_from,
                "limit": ast.Constant(value=ACTIVITY_TOP_TOOLS_LIMIT),
            },
        )
    ]

    clients = [
        contracts.ActivityClientRow(client=str(row[0]) if row[0] else "", calls=_parse_int(row[1]) or 0)
        for row in _run_activity_query(
            team,
            _ACTIVITY_CLIENTS_SQL,
            "mcp_analytics_activity_clients",
            {
                "tool_call_event": tool_call_event,
                "date_from": date_from,
                "limit": ast.Constant(value=ACTIVITY_CLIENTS_LIMIT),
            },
        )
    ]

    recent_calls = [
        contracts.ActivityRecentCall(
            timestamp=row[0],
            tool=str(row[1] or ""),
            intent=str(row[2]) if row[2] else None,
            is_error=bool(row[3]),
            error_message=_extract_error_message(row[4]),
            duration_ms=float(row[5]) if row[5] is not None else None,
            client_name=str(row[6]) if row[6] else None,
        )
        for row in _run_activity_query(
            team,
            _ACTIVITY_RECENT_CALLS_SQL,
            "mcp_analytics_activity_recent_calls",
            {
                "tool_call_event": tool_call_event,
                "date_from": date_from,
                "limit": ast.Constant(value=ACTIVITY_RECENT_CALLS_LIMIT),
            },
        )
    ]

    return contracts.ActivityOverview(stats=stats, top_tools=top_tools, clients=clients, recent_calls=recent_calls)


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


def _scope_blob_to_tool(
    clusters_raw: list[Any], tools_raw: list[Any], overlaps_raw: list[Any], tool: str
) -> tuple[list[Any], list[Any], list[Any]]:
    """Narrow a snapshot blob to one tool's slice of it.

    Keeps the tool's pivot entry, the clusters that entry references, the clusters
    whose error switches name the tool (the detail panel lists those), and the
    overlap pairs it belongs to. Everything else is other tools' data that a
    single-tool view would download and discard.
    """
    tools = [item for item in tools_raw if isinstance(item, dict) and item.get("tool") == tool]
    wanted_cluster_ids = {
        entry.get("cluster_id") for item in tools for entry in item.get("clusters", []) if isinstance(entry, dict)
    }
    clusters = [
        item
        for item in clusters_raw
        if isinstance(item, dict)
        and (
            item.get("id") in wanted_cluster_ids
            or any(
                isinstance(switch, dict) and tool in (switch.get("from_tool"), switch.get("to_tool"))
                for switch in item.get("switches", [])
            )
        )
    ]
    overlaps = [
        item for item in overlaps_raw if isinstance(item, dict) and tool in (item.get("tool_a"), item.get("tool_b"))
    ]
    return clusters, tools, overlaps


def get_intent_cluster_snapshot(team: Team, tool: str | None = None) -> contracts.IntentClusterSnapshot:
    """Return the current intent cluster snapshot for a team.

    ``tool`` narrows clusters, pivot, and overlaps to that tool's slice; the
    coverage meta stays whole-snapshot because it describes the run. Surfaces
    that render one tool use it so they don't download the full blob.

    When no snapshot exists yet, returns an empty IDLE one so callers can
    render the "compute" CTA without distinguishing "missing" from "empty".

    Defensive side effect: any row stuck in COMPUTING past
    STALE_COMPUTING_THRESHOLD is auto-flipped to ERROR so the UI can offer
    a retry. The Temporal activity may have died between writing COMPUTING
    and writing its final status (no worker on the queue, worker OOM, etc.)
    and otherwise has no path back to a usable state.
    """
    MCPIntentClusterSnapshot.objects.filter(
        team=team,
        status=MCPIntentClusterSnapshot.Status.COMPUTING,
        updated_at__lt=timezone.now() - STALE_COMPUTING_THRESHOLD,
    ).update(
        status=MCPIntentClusterSnapshot.Status.ERROR,
        error_message="Clustering didn't finish in time. Retry to start a new run.",
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
    tools_raw = blob.get("tools", []) if isinstance(blob, dict) else []
    overlaps_raw = blob.get("tool_overlaps", []) if isinstance(blob, dict) else []
    meta_raw = blob.get("computed_with") if isinstance(blob, dict) else None

    # Snapshots persisted before build_snapshot capped its output can hold
    # hundreds of clusters — cap at read time too, keeping the highest-volume
    # ones (the same ranking build_snapshot persists).
    if len(clusters_raw) > MAX_SNAPSHOT_CLUSTERS:
        clusters_raw = sorted(
            (item for item in clusters_raw if isinstance(item, dict)),
            key=lambda item: int(item.get("call_count", 0) or 0),
            reverse=True,
        )[:MAX_SNAPSHOT_CLUSTERS]

    if tool is not None:
        clusters_raw, tools_raw, overlaps_raw = _scope_blob_to_tool(clusters_raw, tools_raw, overlaps_raw, tool)

    return contracts.IntentClusterSnapshot(
        status=snapshot.status,
        error_message=snapshot.error_message,
        last_computed_at=snapshot.last_computed_at,
        last_computed_by_email=snapshot.last_computed_by.email if snapshot.last_computed_by else "",
        clusters=[_to_cluster_dto(item) for item in clusters_raw if isinstance(item, dict)],
        computed_with=_to_meta_dto(meta_raw) if isinstance(meta_raw, dict) else None,
        tools=[_to_tool_pivot_dto(item) for item in tools_raw if isinstance(item, dict)],
        tool_overlaps=[_to_overlap_dto(item) for item in overlaps_raw if isinstance(item, dict)],
    )


# bool is a subclass of int, so the isinstance check has to exclude it explicitly —
# otherwise a boolean in the blob silently coerces to 1.0 / 1 instead of being rejected.
def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _opt_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


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
        switches=[
            contracts.ClusterSwitch(
                from_tool=str(entry.get("from_tool", "")),
                to_tool=str(entry.get("to_tool", "")),
                count=int(entry.get("count", 0)),
            )
            for entry in item.get("switches", [])
            if isinstance(entry, dict)
        ],
        self_retries=[
            contracts.ClusterSelfRetry(tool=str(entry.get("tool", "")), count=int(entry.get("count", 0)))
            for entry in item.get("self_retries", [])
            if isinstance(entry, dict)
        ],
    )


def _to_tool_pivot_dto(item: dict[str, Any]) -> contracts.ToolPivot:
    return contracts.ToolPivot(
        tool=str(item.get("tool", "")),
        call_count=int(item.get("call_count", 0)),
        error_count=int(item.get("error_count", 0)),
        session_count=int(item.get("session_count", 0)),
        contested_score=_opt_float(item.get("contested_score")),
        advertised_sessions=int(item.get("advertised_sessions", 0)),
        called_when_advertised=int(item.get("called_when_advertised", 0)),
        discovery_rate_pct=_opt_float(item.get("discovery_rate_pct")),
        description=str(item["description"]) if item.get("description") else None,
        # Pre-cap count, so the UI never presents a capped entry list as the whole
        # story. Blobs written before it existed fall back to the entries they have.
        n_clusters_served=_opt_int(item.get("n_clusters_served")) or len(item.get("clusters", [])),
        clusters=[_to_tool_pivot_cluster_dto(entry) for entry in item.get("clusters", []) if isinstance(entry, dict)],
    )


def _to_tool_pivot_cluster_dto(entry: dict[str, Any]) -> contracts.ToolPivotClusterEntry:
    competitor_raw = entry.get("top_competitor")
    return contracts.ToolPivotClusterEntry(
        cluster_id=int(entry.get("cluster_id", 0)),
        calls=int(entry.get("calls", 0)),
        capture_pct=float(entry.get("capture_pct", 0.0)),
        rank=int(entry.get("rank", 0)),
        description_fit=_opt_float(entry.get("description_fit")),
        top_competitor=(
            contracts.ToolPivotCompetitor(
                tool=str(competitor_raw.get("tool", "")), pct=float(competitor_raw.get("pct", 0.0))
            )
            if isinstance(competitor_raw, dict)
            else None
        ),
    )


def _to_overlap_dto(item: dict[str, Any]) -> contracts.ToolOverlap:
    return contracts.ToolOverlap(
        tool_a=str(item.get("tool_a", "")),
        tool_b=str(item.get("tool_b", "")),
        contested_calls=int(item.get("contested_calls", 0)),
        sessions_with_both=int(item.get("sessions_with_both", 0)),
        sessions_with_either=int(item.get("sessions_with_either", 0)),
        top_cluster_id=int(item.get("top_cluster_id", 0)),
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
        corpus=str(meta["corpus"]) if meta.get("corpus") else None,
        sampled_sessions=_opt_int(meta.get("sampled_sessions")),
        window_sessions=_opt_int(meta.get("window_sessions")),
        session_coverage_pct=_opt_float(meta.get("session_coverage_pct")),
        intent_coverage_pct=_opt_float(meta.get("intent_coverage_pct")),
        imputed_call_pct=_opt_float(meta.get("imputed_call_pct")),
        unattributed_call_pct=_opt_float(meta.get("unattributed_call_pct")),
        corpus_call_coverage_pct=_opt_float(meta.get("corpus_call_coverage_pct")),
        advertisement_coverage_pct=_opt_float(meta.get("advertisement_coverage_pct")),
        n_tools=_opt_int(meta.get("n_tools")),
        dropped_tools=_opt_int(meta.get("dropped_tools")),
        dropped_overlap_pairs=_opt_int(meta.get("dropped_overlap_pairs")),
        description_coverage_pct=_opt_float(meta.get("description_coverage_pct")),
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
