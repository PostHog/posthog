"""Intent clustering pipeline for MCP analytics.

Pure functions, each independently testable, that together build a cluster
snapshot of MCP intents. The Temporal activity in
``posthog/temporal/mcp_analytics/intent_clustering/activities.py`` orchestrates
them and persists the result.

Why pure functions: the algorithm is the riskiest part of this feature. Keeping
each stage as a pure function over numpy arrays / dataclasses makes the
algorithm validatable without touching ClickHouse, Postgres, or the embedding
service.

Intent sources: the corpus is per tool call, and events are its only source.
Each call carries its own ``$mcp_intent``; calls without one inherit the most
recent prior intent in the same session (last observation carried forward), so
tools are credited to the intent they actually served rather than to the
session's opening statement. The on-demand ``MCPSession.intent`` LLM summaries
are deliberately *not* overlaid: a summary describes a whole session, so
attributing it to each of that session's calls is the smear this corpus exists
to remove. Sessions whose intent was only ever summarised therefore sit outside
clustering; ``intent_coverage_pct`` reports how much of the window that leaves
out.
The snapshot also carries a tool-centric pivot: per tool, which intent clusters
it serves, its share of each (capture), how contested those clusters are, and,
where a ``$mcp_tools_list`` catalog was observed, how often agents discover the
tool when it is advertised.
"""

import math
import asyncio
import hashlib
from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog
from sklearn.cluster import AgglomerativeClustering

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import EmbeddingResponse, async_generate_embedding
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.mcp_analytics.backend.constants import MAX_SNAPSHOT_CLUSTERS, MCP_TOOL_CALL_EVENT, MCP_TOOLS_LIST_EVENT
from products.mcp_analytics.backend.hogql_queries.base import EFFECTIVE_DESCRIPTION_SQL, EFFECTIVE_TOOL_SQL
from products.mcp_analytics.backend.models import MCPIntentEmbeddingCache

logger = structlog.get_logger(__name__)

# Constants
SNAPSHOT_VERSION = 2
EMBEDDING_MODEL = "text-embedding-3-small-1536"
EMBEDDING_PREFIX = "User intent: "
# Descriptions share the intent embedding cache; the prefix keys them apart so
# identical text embedded as an intent and as a description never collides.
DESCRIPTION_EMBEDDING_PREFIX = "Tool description: "
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_TOP_N_INTENTS = 1000
DEFAULT_DISTANCE_THRESHOLD = 0.2
MAX_SAMPLE_INTENTS_PER_CLUSTER = 3

# Mirrors the capture-side clip in services/mcp (MAX_CAPTURED_DESCRIPTION_LENGTH);
# re-applied here because external SDKs may stamp longer values.
MAX_DESCRIPTION_LENGTH = 512
# Below this many advertised sessions a discovery rate is noise, so it stays null.
MIN_ADVERTISED_SESSIONS = 5
# Payload bounds for the snapshot blob. Only the two top-level caps report what they
# dropped (`dropped_tools`, `dropped_overlap_pairs` in computed_with); the per-cluster
# caps below truncate silently, so `computed_with` is not a completeness check for them.
# The per-tool cluster cap is the exception: `n_clusters_served` carries the pre-cap
# count, so a tool showing 20 entries can still say how many it really serves.
MAX_TOOLS_IN_SNAPSHOT = 300
MAX_CLUSTERS_PER_TOOL = 20
MAX_SWITCHES_PER_CLUSTER = 10
MAX_SELF_RETRIES_PER_CLUSTER = 5
MAX_CONFUSION_PAIRS = 50
# Pair expansion is O(n^2) in a cluster's tool count, and event senders control
# tool names, so only each cluster's highest-volume tools enter it. Tail tools
# contribute at most their own tiny min(count) anyway.
MAX_OVERLAP_TOOLS_PER_CLUSTER = 20

# Placeholder the session summariser writes when a session has no recordable intent.
# No event ever carries it, so this only bites if a summary is ever fed back into the
# corpus — kept as a guard so that path can't form a pseudo-cluster of "empty" sessions.
NO_INTENT_RECORDED_FALLBACK = "No agent intent was recorded for this session."

# Embedding cache + concurrency
# 1536-d float32 embedding = 6144 bytes. 500-intent corpus × 6144 ≈ 3 MB/team.
# Cap concurrent embedding worker requests so we don't dogpile when a team's
# corpus has hundreds of misses on first run while staying well under any
# per-team rate limit on the embedding provider.
EMBED_CONCURRENCY = 20

# How many tool-call steps to show in the per-cluster Sankey before the
# outcome column. Sessions with fewer steps pad with None so the column
# count stays fixed; the UI renders those as an "Ended" node.
JOURNEY_DEPTH = 4
MAX_JOURNEY_PATHS_PER_CLUSTER = 10


@dataclass(frozen=True)
class IntentRecord:
    """One unique intent text, with the per-call tool statistics attributed to it."""

    intent_text: str
    frequency: int
    session_count: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CallRecord:
    """One tool call after intent attribution. ``intent_text`` is None when the
    call happened before its session's first recorded intent."""

    session_id: str
    tool: str
    intent_text: str | None
    is_error: bool


@dataclass(frozen=True)
class CorpusStats:
    """Attribution accounting for the sampled corpus, surfaced in computed_with
    so the UI can state how much of the traffic the clusters actually explain."""

    total_calls: int
    attributed_calls: int
    imputed_calls: int
    kept_calls: int


@dataclass(frozen=True)
class WindowStats:
    """Whole-window aggregates (not sampled) used for coverage reporting."""

    total_calls: int
    calls_with_intent: int
    sessions: int


# Intent corpus -----------------------------------------------------------

# Bound on sessions sampled from ClickHouse for the corpus. Keeps the IN-tuple
# in the per-session queries below at a sane size; a larger sample mostly adds
# long-tail singleton intents past DEFAULT_TOP_N_INTENTS anyway.
MAX_CORPUS_SESSIONS = 2000

# execute_hogql_query injects LIMIT 100 into any query without an explicit
# LIMIT — far below what the per-session queries return at production scale
# (one-plus rows per corpus session). Cap explicitly at the HogQL per-query
# maximum so results are never silently truncated.
MAX_QUERY_ROWS = 50_000

# Event-sourced intents are free text written by the calling agent — clip them
# so one oversized value can't blow up embedding requests (the worker's model
# has a token ceiling) or bloat the snapshot blob. Real intents are one or two
# sentences; anything past this length adds no clustering signal. Clipping
# happens inside the corpus SQL (HogQL left → leftUTF8) so oversized values
# never leave ClickHouse — up to MAX_QUERY_ROWS of them would otherwise
# materialize in worker memory; build_call_corpus re-clips as defense for
# callers that feed it rows from elsewhere.
MAX_INTENT_TEXT_LENGTH = 1000

# Tool names are sender-controlled too, so they get the same SQL-boundary clip.
# Must be applied identically across the calls, descriptions, and
# advertised-catalog queries, or pivot and discovery keys stop matching for
# oversized names. Real tool names are well under 100 chars.
MAX_TOOL_NAME_LENGTH = 256

# The advertised catalog is a sender-controlled array inside a sender-controlled number
# of $mcp_tools_list events, and the union aggregates both. Clipping name *length* alone
# leaves two unbounded dimensions, so each event's array is sliced and each session's
# events are capped before the union materializes. A real catalog is a few hundred tools
# listed once or twice per session, so both bounds sit far above honest traffic.
MAX_TOOLS_PER_ADVERTISED_LIST = 500
MAX_ADVERTISED_LIST_EVENTS_PER_SESSION = 20
# The two caps above still multiply (events x names, across every sampled session), so
# the distinct union itself is also bounded per session. This is the bound that limits
# what leaves ClickHouse and lands in worker memory; the honest case (a few hundred
# distinct tools per catalog) sits comfortably under it.
MAX_ADVERTISED_TOOLS_PER_SESSION = 1000

# Sessions that recorded at least one $mcp_intent, sampled deterministically.
# Ordering by cityHash64(session_id) is a pseudo-random sample: unbiased across
# the window (newest-first would collapse the corpus to the last few hours at
# production volume) and stable across reruns, so repeat runs re-hit the
# embedding cache.
# NB: `$session_id` is the materialised events column ('' when absent), NOT the
# `properties.` accessor — same rationale as logic.py's session SQL.
_CORPUS_SESSION_SAMPLE_SQL = """
SELECT $session_id AS session_id
FROM events
WHERE event = {event}
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
    AND $session_id != ''
    AND coalesce(toString(properties.$mcp_intent), '') != ''
GROUP BY session_id
ORDER BY cityHash64(session_id)
LIMIT {max_sessions}
"""

# Every tool call of the sampled sessions, in call order, with the call's own
# intent (may be empty; attribution happens in build_call_corpus). The
# effective-tool coalesce matches every other MCP analytics surface, so
# exec-wrapped inner calls resolve to the inner tool here too.
_SESSION_CALLS_SQL = """
SELECT
    $session_id AS session_id,
    left({tool_expr}, {max_tool_len}) AS tool,
    left(coalesce(toString(properties.$mcp_intent), ''), {max_intent_len}) AS intent,
    toString(properties.$mcp_is_error) IN ('true', '1') AS is_error
FROM events
WHERE event = {event}
    AND $session_id IN {session_ids}
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
    AND notEmpty({tool_expr_where})
ORDER BY session_id, timestamp
LIMIT {max_rows}
"""

# Union of $mcp_listed_tool_names across a session's $mcp_tools_list events —
# the catalog the agent actually saw, which is the denominator for discovery
# rates. The coalesce to '[]' matters: the property accessor is Nullable and
# JSONExtract of a Nullable into Array(String) is a ClickHouse type error.
_SESSION_ADVERTISED_TOOLS_SQL = """
SELECT
    session_id,
    arraySlice(
        arrayDistinct(arrayMap(x -> left(x, {max_tool_len}), arrayFlatten(groupArray(listed)))),
        1,
        {max_advertised_tools}
    ) AS advertised_tools
FROM (
    SELECT
        $session_id AS session_id,
        arraySlice(
            JSONExtract(coalesce(toString(properties.$mcp_listed_tool_names), '[]'), 'Array(String)'),
            1,
            {max_tools_per_list}
        ) AS listed
    FROM events
    WHERE event = {event}
        AND $session_id IN {session_ids}
        AND timestamp >= now() - INTERVAL {lookback_days} DAY
        AND $session_id != ''
    ORDER BY timestamp
    LIMIT {max_list_events} BY session_id
)
GROUP BY session_id
LIMIT {max_rows}
"""

# Whole-window totals for the coverage metrics in computed_with. One cheap
# aggregate row; deliberately unsampled so the UI can honestly relate the
# sampled corpus to the traffic it represents. The notEmpty tool predicate
# mirrors _SESSION_CALLS_SQL — the coverage banner reads these percentages
# against the corpus, so both have to describe the same population.
_WINDOW_STATS_SQL = """
SELECT
    count() AS total_calls,
    countIf(coalesce(toString(properties.$mcp_intent), '') != '') AS calls_with_intent,
    uniq($session_id) AS sessions
FROM events
WHERE event = {event}
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
    AND $session_id != ''
    AND notEmpty({tool_expr_where})
"""

# Latest observed description per effective tool. argMax(description, timestamp)
# picks the newest revision, which is the one agents currently see.
# The tool filter is applied before GROUP BY so aggregate state only exists for the
# bounded corpus tool set — without it, a sender emitting unique tool names per call
# forces argMax state for every name before LIMIT applies.
_TOOL_DESCRIPTIONS_SQL = """
SELECT
    left({tool_expr}, {max_tool_len}) AS tool,
    argMax(left({description_expr}, {max_desc_len}), timestamp) AS description
FROM events
WHERE event = {event}
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
    AND left({tool_expr_where}, {max_tool_len}) IN {tools}
    AND notEmpty({description_expr_where})
GROUP BY tool
LIMIT {max_rows}
"""


def _run_corpus_query(team: Team, query: ast.SelectQuery | ast.SelectSetQuery) -> list[Any]:
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(query=query, team=team)
    return response.results or []


def _session_ids_tuple(session_ids: list[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=sid) for sid in session_ids])


def sample_corpus_sessions(
    team: Team,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_sessions: int = MAX_CORPUS_SESSIONS,
) -> list[str]:
    """Deterministically sample sessions that recorded at least one intent."""
    query = parse_select(
        _CORPUS_SESSION_SAMPLE_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "lookback_days": ast.Constant(value=lookback_days),
            "max_sessions": ast.Constant(value=max_sessions),
        },
    )
    return [str(row[0]) for row in _run_corpus_query(team, query) if row[0]]


def fetch_session_calls(
    team: Team,
    session_ids: list[str],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[tuple[str, str, str, bool]]:
    """Return ``(session_id, tool, raw_intent, is_error)`` rows in call order."""
    if not session_ids:
        return []
    query = parse_select(
        _SESSION_CALLS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "tool_expr": parse_expr(EFFECTIVE_TOOL_SQL),
            "tool_expr_where": parse_expr(EFFECTIVE_TOOL_SQL),
            "session_ids": _session_ids_tuple(session_ids),
            "lookback_days": ast.Constant(value=lookback_days),
            "max_rows": ast.Constant(value=MAX_QUERY_ROWS),
            "max_tool_len": ast.Constant(value=MAX_TOOL_NAME_LENGTH),
            "max_intent_len": ast.Constant(value=MAX_INTENT_TEXT_LENGTH),
        },
    )
    rows = [
        (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""), bool(row[3]))
        for row in _run_corpus_query(team, query)
    ]
    if len(rows) >= MAX_QUERY_ROWS:
        # The window's calls exceeded the per-query cap: the corpus silently
        # under-represents the sampled sessions. Surface it rather than let the
        # coverage numbers lie.
        logger.warning(
            "mcpa.intent_clustering.session_calls_truncated",
            team_id=team.id,
            max_rows=MAX_QUERY_ROWS,
            sessions=len(session_ids),
        )
    return rows


def fetch_advertised_tools(
    team: Team,
    session_ids: list[str],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, set[str]]:
    """Return ``{session_id: advertised tool names}`` for sessions with a tools-list event.

    Sessions with no ``$mcp_tools_list`` event are absent from the result, not
    empty — absence means "advertisement unknown", which callers must exclude
    from discovery denominators rather than treat as "nothing advertised".
    """
    if not session_ids:
        return {}
    query = parse_select(
        _SESSION_ADVERTISED_TOOLS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOLS_LIST_EVENT),
            "session_ids": _session_ids_tuple(session_ids),
            "lookback_days": ast.Constant(value=lookback_days),
            "max_rows": ast.Constant(value=MAX_QUERY_ROWS),
            "max_tool_len": ast.Constant(value=MAX_TOOL_NAME_LENGTH),
            "max_tools_per_list": ast.Constant(value=MAX_TOOLS_PER_ADVERTISED_LIST),
            "max_list_events": ast.Constant(value=MAX_ADVERTISED_LIST_EVENTS_PER_SESSION),
            "max_advertised_tools": ast.Constant(value=MAX_ADVERTISED_TOOLS_PER_SESSION),
        },
    )
    out: dict[str, set[str]] = {}
    for row in _run_corpus_query(team, query):
        session_id = str(row[0] or "")
        tools = {str(tool) for tool in (row[1] or []) if tool}
        if session_id and tools:
            out[session_id] = tools
    return out


def fetch_window_stats(team: Team, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> WindowStats:
    """Whole-window call/intent/session totals for coverage reporting."""
    query = parse_select(
        _WINDOW_STATS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "tool_expr_where": parse_expr(EFFECTIVE_TOOL_SQL),
            "lookback_days": ast.Constant(value=lookback_days),
        },
    )
    rows = _run_corpus_query(team, query)
    if not rows:
        return WindowStats(total_calls=0, calls_with_intent=0, sessions=0)
    row = rows[0]
    return WindowStats(
        total_calls=int(row[0] or 0),
        calls_with_intent=int(row[1] or 0),
        sessions=int(row[2] or 0),
    )


def fetch_tool_descriptions(
    team: Team, tools: Collection[str], lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> dict[str, str]:
    """Latest observed description per effective tool, clipped for embedding.

    ``tools`` bounds the aggregation: only the given (already clipped) tool names
    enter the GROUP BY, so sender-invented names never build aggregate state.
    """
    if not tools:
        return {}
    query = parse_select(
        _TOOL_DESCRIPTIONS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "tool_expr": parse_expr(EFFECTIVE_TOOL_SQL),
            "tool_expr_where": parse_expr(EFFECTIVE_TOOL_SQL),
            "description_expr": parse_expr(EFFECTIVE_DESCRIPTION_SQL),
            "description_expr_where": parse_expr(EFFECTIVE_DESCRIPTION_SQL),
            "tools": ast.Tuple(exprs=[ast.Constant(value=tool) for tool in sorted(tools)]),
            "lookback_days": ast.Constant(value=lookback_days),
            "max_rows": ast.Constant(value=MAX_QUERY_ROWS),
            "max_tool_len": ast.Constant(value=MAX_TOOL_NAME_LENGTH),
            "max_desc_len": ast.Constant(value=MAX_DESCRIPTION_LENGTH),
        },
    )
    return {
        str(row[0]): str(row[1])[:MAX_DESCRIPTION_LENGTH] for row in _run_corpus_query(team, query) if row[0] and row[1]
    }


def build_call_corpus(
    rows: list[tuple[str, str, str, bool]],
    top_n: int = DEFAULT_TOP_N_INTENTS,
) -> tuple[list[IntentRecord], dict[str, list[CallRecord]], CorpusStats]:
    """Attribute each call to an intent and roll up per-intent tool statistics.

    Attribution is per call: a call's own ``$mcp_intent`` when present, else the
    most recent prior intent in the same session (last observation carried
    forward — agents typically state a goal once and then chain calls under it).
    Calls before a session's first intent stay unattributed; they remain in
    ``calls_by_session`` but never enter records, journeys, or switch counts.

    ``rows`` must be in call order within each session (the SQL guarantees it);
    LOCF depends on that ordering.
    """
    calls_by_session: dict[str, list[CallRecord]] = {}
    last_intent: dict[str, str] = {}
    total_calls = attributed_calls = imputed_calls = 0

    for session_id, tool, raw_intent, is_error in rows:
        if not session_id or not tool:
            continue
        total_calls += 1
        text = str(raw_intent or "").strip()
        # Guards against a summariser placeholder reaching the corpus; see the
        # constant. It is not an intent, and clustering it forms a pseudo-cluster.
        if text == NO_INTENT_RECORDED_FALLBACK:
            text = ""
        text = text[:MAX_INTENT_TEXT_LENGTH]

        intent_text: str | None
        if text:
            intent_text = text
            last_intent[session_id] = text
        else:
            intent_text = last_intent.get(session_id)
            if intent_text is not None:
                imputed_calls += 1
        if intent_text is not None:
            attributed_calls += 1

        calls_by_session.setdefault(session_id, []).append(
            CallRecord(session_id=session_id, tool=tool, intent_text=intent_text, is_error=is_error)
        )

    rollup: dict[str, dict[str, dict[str, int]]] = {}
    sessions_by_intent: dict[str, set[str]] = defaultdict(set)
    for session_id, calls in calls_by_session.items():
        for call in calls:
            if call.intent_text is None:
                continue
            bucket = rollup.setdefault(call.intent_text, {"tool_counts": {}, "error_counts": {}})
            bucket["tool_counts"][call.tool] = bucket["tool_counts"].get(call.tool, 0) + 1
            if call.is_error:
                bucket["error_counts"][call.tool] = bucket["error_counts"].get(call.tool, 0) + 1
            sessions_by_intent[call.intent_text].add(session_id)

    records = [
        IntentRecord(
            intent_text=text,
            frequency=sum(data["tool_counts"].values()),
            session_count=len(sessions_by_intent[text]),
            tool_counts=data["tool_counts"],
            error_counts=data["error_counts"],
        )
        for text, data in rollup.items()
    ]
    # Secondary key keeps the cut deterministic when frequencies tie.
    records.sort(key=lambda r: (-r.frequency, r.intent_text))
    kept = records[:top_n]

    stats = CorpusStats(
        total_calls=total_calls,
        attributed_calls=attributed_calls,
        imputed_calls=imputed_calls,
        kept_calls=sum(r.frequency for r in kept),
    )
    return kept, calls_by_session, stats


# Cluster flows ------------------------------------------------------------


def compute_cluster_flows(
    records: list[IntentRecord],
    labels: np.ndarray,
    calls_by_session: dict[str, list[CallRecord]],
) -> dict[int, dict[str, Any]]:
    """Per-cluster journeys, error switches, self-retries, and session sets.

    A session belongs to every cluster its attributed calls touch; each
    cluster's journey and outcome come from that session's *own* calls for the
    cluster (its C-subsequence), so an error on an unrelated intent in the same
    session cannot mark this cluster's journey as errored. A switch is an
    errored call immediately followed, within the subsequence, by a call to a
    different tool; the same tool again is a self-retry.
    """
    intent_to_cluster = {records[i].intent_text: int(labels[i]) for i in range(len(records))}

    path_counts: dict[int, Counter[tuple[tuple[str | None, ...], str]]] = defaultdict(Counter)
    switch_counts: dict[int, Counter[tuple[str, str]]] = defaultdict(Counter)
    retry_counts: dict[int, Counter[str]] = defaultdict(Counter)
    session_ids: dict[int, set[str]] = defaultdict(set)

    for session_id, calls in calls_by_session.items():
        per_cluster: dict[int, list[CallRecord]] = defaultdict(list)
        for call in calls:
            if call.intent_text is None:
                continue
            cluster_id = intent_to_cluster.get(call.intent_text)
            if cluster_id is None:
                continue
            per_cluster[cluster_id].append(call)

        for cluster_id, subsequence in per_cluster.items():
            session_ids[cluster_id].add(session_id)
            steps: list[str | None] = [call.tool for call in subsequence[:JOURNEY_DEPTH]]
            steps += [None] * (JOURNEY_DEPTH - len(steps))
            outcome = "error" if any(call.is_error for call in subsequence) else "completed"
            path_counts[cluster_id][(tuple(steps), outcome)] += 1

            for prev, nxt in zip(subsequence, subsequence[1:]):
                if not prev.is_error:
                    continue
                if nxt.tool == prev.tool:
                    retry_counts[cluster_id][prev.tool] += 1
                else:
                    switch_counts[cluster_id][(prev.tool, nxt.tool)] += 1

    flows: dict[int, dict[str, Any]] = {}
    for cluster_id in session_ids:
        ranked = path_counts[cluster_id].most_common()
        leak = next(
            (
                {"steps": list(steps), "outcome": outcome, "count": count}
                for (steps, outcome), count in ranked
                if outcome != "completed"
            ),
            None,
        )
        flows[cluster_id] = {
            "journey": {
                "paths": [
                    {"steps": list(steps), "outcome": outcome, "count": count}
                    for (steps, outcome), count in ranked[:MAX_JOURNEY_PATHS_PER_CLUSTER]
                ],
                "total_sessions": sum(path_counts[cluster_id].values()),
                "leak": leak,
            },
            "switches": [
                {"from_tool": from_tool, "to_tool": to_tool, "count": count}
                for (from_tool, to_tool), count in switch_counts[cluster_id].most_common(MAX_SWITCHES_PER_CLUSTER)
            ],
            "self_retries": [
                {"tool": tool, "count": count}
                for tool, count in retry_counts[cluster_id].most_common(MAX_SELF_RETRIES_PER_CLUSTER)
            ],
            "session_ids": session_ids[cluster_id],
        }
    return flows


# Embeddings --------------------------------------------------------------


def _content_hash(text: str, prefix: str = EMBEDDING_PREFIX) -> str:
    """SHA-256 of the prefixed text — what we actually embed."""
    return hashlib.sha256((prefix + text).encode("utf-8")).hexdigest()


def _encode_embedding(vector: list[float]) -> bytes:
    """Encode an embedding to compact bytes for cache storage."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def _decode_embedding(blob: bytes) -> np.ndarray:
    """Decode cached bytes back into a 1-D float32 vector."""
    return np.frombuffer(blob, dtype=np.float32)


@database_sync_to_async
def _load_cached_embeddings(team: Team, hashes: list[str], model: str) -> dict[str, np.ndarray]:
    """Return ``{content_hash: embedding}`` for cache hits."""
    if not hashes:
        return {}
    rows = MCPIntentEmbeddingCache.objects.filter(
        team=team,
        content_hash__in=hashes,
        model=model,
    ).values_list("content_hash", "embedding")
    return {content_hash: _decode_embedding(bytes(blob)) for content_hash, blob in rows}


@database_sync_to_async
def _persist_embedding(team: Team, content_hash: str, model: str, vector: list[float]) -> None:
    """Insert (or no-op) a single cache row. Concurrent identical inserts are tolerated.

    Uses ``get_or_create`` rather than ``update_or_create`` because the content hash
    deterministically maps to the embedding bytes — there is nothing to update if the
    row already exists. ``get_or_create`` avoids the spurious UPDATE that
    ``update_or_create`` would issue on a creation race.
    """
    MCPIntentEmbeddingCache.objects.get_or_create(
        team=team,
        content_hash=content_hash,
        model=model,
        defaults={"embedding": _encode_embedding(vector)},
    )


@dataclass(frozen=True, kw_only=True)
class _EmbedOutcome:
    """One text's embedding attempt: the vector, or the error that stopped it.

    Carrying the error back (rather than collapsing a failure to ``None``) is what lets the
    batch report *why* it degraded. A whole-batch failure otherwise surfaces only as "all
    embedding requests failed", with the cause discarded at the point it was known.
    """

    vector: np.ndarray | None
    error: str | None = None


async def _embed_one_with_cache(
    team: Team,
    text: str,
    content_hash: str,
    semaphore: asyncio.Semaphore,
    cached: dict[str, np.ndarray],
    prefix: str,
) -> _EmbedOutcome:
    """Return the embedding for ``text``, hitting the cache when possible.

    Concurrency is bounded by ``semaphore``; cache reads come pre-loaded in
    ``cached`` so the hot path is a dict lookup. Misses go through
    ``async_generate_embedding`` and write back on success.
    """
    hit = cached.get(content_hash)
    if hit is not None:
        return _EmbedOutcome(vector=hit)
    async with semaphore:
        try:
            response: EmbeddingResponse = await async_generate_embedding(team, prefix + text, model=EMBEDDING_MODEL)
        except Exception as error:
            return _EmbedOutcome(vector=None, error=f"{type(error).__name__}: {error}")
    try:
        await _persist_embedding(team, content_hash, EMBEDDING_MODEL, response.embedding)
    except Exception:
        # A concurrent insert for the same (team, hash, model) is fine —
        # the unique constraint guarantees the row exists. Don't fail the
        # whole batch over a race.
        pass
    return _EmbedOutcome(vector=np.asarray(response.embedding, dtype=np.float32))


async def embed_texts_async(
    team: Team, texts: list[str], prefix: str = EMBEDDING_PREFIX
) -> tuple[np.ndarray, list[int]]:
    """Embed a list of texts concurrently, with a per-team cache.

    ``prefix`` names the embedding kind (intent vs tool description) and is part
    of the cache key, so identical text embedded under two prefixes gets two
    cache rows.

    Returns (embeddings, valid_indices) where ``valid_indices`` are the indices
    into ``texts`` for which embedding succeeded. Skipped indices have no row
    in the returned matrix. Callers must align downstream data structures with
    ``valid_indices``.

    Cache key is ``(team, sha256(prefix + text), model)``. Hits return the
    stored bytes; misses call the embedding worker and write back. Worker
    concurrency is capped at ``EMBED_CONCURRENCY``.
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32), []

    hashes = [_content_hash(t, prefix) for t in texts]
    cached = await _load_cached_embeddings(team, hashes, EMBEDDING_MODEL)
    semaphore = asyncio.Semaphore(EMBED_CONCURRENCY)

    results = await asyncio.gather(
        *[
            _embed_one_with_cache(team, text, content_hash, semaphore, cached, prefix)
            for text, content_hash in zip(texts, hashes)
        ]
    )

    vectors: list[np.ndarray] = []
    valid_indices: list[int] = []
    errors: list[str] = []
    for i, outcome in enumerate(results):
        if outcome.vector is None:
            if outcome.error is not None:
                errors.append(outcome.error)
            continue
        vectors.append(outcome.vector)
        valid_indices.append(i)

    if errors:
        # Failures are swallowed per text so one bad request can't sink the
        # batch — surface the aggregate, with one representative error, so a
        # degraded embedding worker is diagnosable instead of silently
        # shrinking the corpus.
        logger.warning(
            "mcpa.intent_clustering.embedding_failures",
            team_id=team.id,
            failed=len(errors),
            total=len(texts),
            error=errors[0],
        )

    if not vectors:
        return np.zeros((0, 0), dtype=np.float32), []

    return np.stack(vectors).astype(np.float32, copy=False), valid_indices


# Clustering --------------------------------------------------------------


def cluster_embeddings(
    embeddings: np.ndarray,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> np.ndarray:
    """Run agglomerative clustering on embedding vectors.

    Uses average linkage and cosine distance. ``distance_threshold`` is the
    user-facing knob: smaller -> tighter clusters, more of them.
    Output: an integer label per embedding, all >= 0 (no noise sentinel).
    """
    n = len(embeddings)
    if n == 0:
        return np.array([], dtype=np.int64)
    if n == 1:
        return np.array([0], dtype=np.int64)

    clusterer = AgglomerativeClustering(
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    return clusterer.fit_predict(embeddings)


# Snapshot building -------------------------------------------------------


def _routing_entropy(tool_counts: dict[str, int]) -> float:
    """Shannon entropy of the tool distribution, normalised to [0, 1].

    0 = perfectly consistent (one tool dominates), 1 = uniformly spread.
    Single-tool clusters return 0.
    """
    total = sum(tool_counts.values())
    if total <= 0:
        return 0.0
    probabilities = [count / total for count in tool_counts.values() if count > 0]
    if len(probabilities) <= 1:
        return 0.0
    entropy = -sum(p * math.log(p) for p in probabilities)
    return entropy / math.log(len(probabilities))


def _medoid_index(embeddings: np.ndarray, indices: list[int]) -> int:
    """Return the index (into ``indices``) whose embedding is closest to the
    cluster centroid by cosine distance."""
    if len(indices) == 1:
        return indices[0]
    cluster_matrix = embeddings[indices]
    centroid = cluster_matrix.mean(axis=0)
    centroid_norm = np.linalg.norm(centroid) or 1.0
    row_norms = np.linalg.norm(cluster_matrix, axis=1)
    row_norms = np.where(row_norms == 0, 1.0, row_norms)
    cosine_sims = (cluster_matrix @ centroid) / (row_norms * centroid_norm)
    best_local = int(np.argmax(cosine_sims))
    return indices[best_local]


def top_corpus_tools(records: list[IntentRecord], max_tools: int = MAX_TOOLS_IN_SNAPSHOT) -> set[str]:
    """The top ``max_tools`` corpus tools by attributed call volume — the same
    population and cap the tool pivot uses. Everything description-related
    (the ClickHouse aggregation, the embedding fan-out) is bounded to this set."""
    totals: Counter[str] = Counter()
    for record in records:
        for tool, count in record.tool_counts.items():
            totals[tool] += count
    return {tool for tool, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:max_tools]}


def compute_description_fit(
    embeddings: np.ndarray,
    labels: np.ndarray,
    description_embeddings: dict[str, np.ndarray],
) -> dict[str, dict[int, float]]:
    """Cosine similarity between each tool's description and each cluster centroid.

    Returns ``{tool: {cluster_id: fit}}``; tools without a description embedding
    are absent. High fit + low capture is the "agents should find this tool for
    this intent but don't" signal.
    """
    if not description_embeddings or len(embeddings) == 0:
        return {}

    centroids: dict[int, np.ndarray] = {}
    for cluster_id in {int(label) for label in labels.tolist()}:
        member_matrix = embeddings[labels == cluster_id]
        centroid = member_matrix.mean(axis=0)
        centroids[cluster_id] = centroid / (np.linalg.norm(centroid) or 1.0)

    fit: dict[str, dict[int, float]] = {}
    for tool, vector in description_embeddings.items():
        unit = np.asarray(vector, dtype=np.float32)
        unit = unit / (np.linalg.norm(unit) or 1.0)
        fit[tool] = {cluster_id: round(float(unit @ centroid), 3) for cluster_id, centroid in centroids.items()}
    return fit


def compute_tool_pivot(
    clusters: list[dict[str, Any]],
    calls_by_session: dict[str, list[CallRecord]],
    advertised_by_session: dict[str, set[str]],
    tool_descriptions: dict[str, str],
    description_fit: dict[str, dict[int, float]],
    max_tools: int = MAX_TOOLS_IN_SNAPSHOT,
    max_clusters_per_tool: int = MAX_CLUSTERS_PER_TOOL,
    snapshot_cluster_ids: Collection[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Pivot the built clusters into a per-tool view.

    Per tool: total attributed calls/errors, the clusters it serves (with its
    capture share, rank, and strongest competitor in each), a call-weighted
    contested score, and a discovery rate against the sessions that advertised
    the tool (null below ``MIN_ADVERTISED_SESSIONS`` — not enough signal).
    Returns ``(tools, dropped_count)`` with tools capped at ``max_tools`` by
    call volume.

    Totals cover every cluster in ``clusters``. ``snapshot_cluster_ids``, when
    given, restricts which clusters get a per-cluster *entry*: callers pass the
    ids that survived the snapshot's cluster cap so every ``cluster_id`` in the
    blob still resolves against a cluster the blob carries, while the totals
    keep counting the calls of the clusters the cap dropped. ``n_clusters_served``
    is the pre-cap count, so the UI can say when an entry list is partial.

    Entries deliberately carry no per-cluster constants (label, cluster totals,
    entropy): repeating them per tool x cluster is what turns this pivot into a
    multi-megabyte blob. Clients join on ``cluster_id``.
    """
    per_tool_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    call_totals: Counter[str] = Counter()
    error_totals: Counter[str] = Counter()
    clusters_served: Counter[str] = Counter()
    weighted_entropy: dict[str, float] = defaultdict(float)

    for cluster in clusters:
        distribution = cluster["tool_distribution"]
        in_snapshot = snapshot_cluster_ids is None or cluster["id"] in snapshot_cluster_ids
        for rank, entry in enumerate(distribution, start=1):
            tool = entry["tool"]
            call_totals[tool] += entry["count"]
            error_totals[tool] += entry["errors"]
            clusters_served[tool] += 1
            weighted_entropy[tool] += entry["count"] * cluster["routing_entropy"]
            if not in_snapshot:
                continue
            competitor = next(
                ({"tool": other["tool"], "pct": other["pct"]} for other in distribution if other["tool"] != tool),
                None,
            )
            per_tool_clusters[tool].append(
                {
                    "cluster_id": cluster["id"],
                    "calls": entry["count"],
                    "capture_pct": entry["pct"],
                    "rank": rank,
                    "description_fit": description_fit.get(tool, {}).get(cluster["id"]),
                    "top_competitor": competitor,
                }
            )

    # Attributed calls only, matching call_count and the session sets
    # compute_tool_overlaps builds. Counting unattributed calls here would let a
    # tool post a healthy discovery rate off calls that never entered a cluster.
    sessions_calling: dict[str, set[str]] = defaultdict(set)
    for session_id, calls in calls_by_session.items():
        for call in calls:
            if call.intent_text is None:
                continue
            sessions_calling[call.tool].add(session_id)

    # Inverted once rather than per tool: the tool set is sender-controlled and uncapped
    # at this point, so scanning every advertised session for each of them is O(tools x
    # sessions) on values a caller chooses.
    # Only corpus sessions count. A session the row cap dropped contributes nothing to
    # the numerator, so leaving it in the denominator biases discovery rates down
    # precisely when truncation fires.
    advertised_sessions_by_tool: dict[str, set[str]] = defaultdict(set)
    for session_id, advertised in advertised_by_session.items():
        if session_id not in calls_by_session:
            continue
        for advertised_tool in advertised:
            advertised_sessions_by_tool[advertised_tool].add(session_id)

    tools: list[dict[str, Any]] = []
    for tool, call_count in call_totals.items():
        advertised_sessions = advertised_sessions_by_tool[tool]
        called_when_advertised = len(advertised_sessions & sessions_calling[tool])
        discovery_rate_pct = (
            round(100.0 * called_when_advertised / len(advertised_sessions), 1)
            if len(advertised_sessions) >= MIN_ADVERTISED_SESSIONS
            else None
        )
        tools.append(
            {
                "tool": tool,
                "call_count": call_count,
                "error_count": error_totals[tool],
                "session_count": len(sessions_calling[tool]),
                "contested_score": round(weighted_entropy[tool] / call_count, 3) if call_count else None,
                "n_clusters_served": clusters_served[tool],
                "advertised_sessions": len(advertised_sessions),
                "called_when_advertised": called_when_advertised,
                "discovery_rate_pct": discovery_rate_pct,
                "description": tool_descriptions.get(tool),
                "clusters": sorted(per_tool_clusters[tool], key=lambda entry: entry["calls"], reverse=True)[
                    :max_clusters_per_tool
                ],
            }
        )

    tools.sort(key=lambda t: (-t["call_count"], t["tool"]))
    dropped = max(0, len(tools) - max_tools)
    return tools[:max_tools], dropped


def compute_tool_overlaps(
    clusters: list[dict[str, Any]],
    calls_by_session: dict[str, list[CallRecord]],
    max_pairs: int = MAX_CONFUSION_PAIRS,
    max_tools_per_cluster: int = MAX_OVERLAP_TOOLS_PER_CLUSTER,
) -> tuple[list[dict[str, Any]], int]:
    """Tool pairs competing for the same intents.

    ``contested_calls`` is the sum over clusters of ``min(calls_a, calls_b)`` —
    the volume both tools could plausibly have taken. The session counts split
    substitution from cooperation: pairs used together in the same sessions are
    workflows, pairs whose sessions pick one or the other are confusion.
    Returns ``(pairs, dropped_count)`` capped at ``max_pairs``; only each
    cluster's top ``max_tools_per_cluster`` tools enter pair expansion.
    """
    contested: dict[tuple[str, str], int] = defaultdict(int)
    top_cluster: dict[tuple[str, str], tuple[int, int]] = {}

    for cluster in clusters:
        # tool_distribution is sorted by count desc, so this keeps the head.
        distribution = cluster["tool_distribution"][:max_tools_per_cluster]
        for i in range(len(distribution)):
            for j in range(i + 1, len(distribution)):
                tool_i, tool_j = str(distribution[i]["tool"]), str(distribution[j]["tool"])
                pair = (tool_i, tool_j) if tool_i <= tool_j else (tool_j, tool_i)
                overlap = min(distribution[i]["count"], distribution[j]["count"])
                if overlap <= 0:
                    continue
                contested[pair] += overlap
                best = top_cluster.get(pair)
                if best is None or overlap > best[0]:
                    top_cluster[pair] = (overlap, cluster["id"])

    session_tools = {
        session_id: {call.tool for call in calls if call.intent_text is not None}
        for session_id, calls in calls_by_session.items()
    }

    ranked = sorted(contested.items(), key=lambda item: (-item[1], item[0]))
    pairs: list[dict[str, Any]] = []
    for (tool_a, tool_b), contested_calls in ranked[:max_pairs]:
        pairs.append(
            {
                "tool_a": tool_a,
                "tool_b": tool_b,
                "contested_calls": contested_calls,
                "sessions_with_both": sum(1 for tools in session_tools.values() if tool_a in tools and tool_b in tools),
                "sessions_with_either": sum(
                    1 for tools in session_tools.values() if tool_a in tools or tool_b in tools
                ),
                "top_cluster_id": top_cluster[(tool_a, tool_b)][1],
            }
        )
    dropped = max(0, len(ranked) - max_pairs)
    return pairs, dropped


def _pct(numerator: float, denominator: float) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def build_snapshot(
    records: list[IntentRecord],
    labels: np.ndarray,
    embeddings: np.ndarray,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    calls_by_session: dict[str, list[CallRecord]] | None = None,
    advertised_by_session: dict[str, set[str]] | None = None,
    tool_descriptions: dict[str, str] | None = None,
    description_embeddings: dict[str, np.ndarray] | None = None,
    corpus_stats: CorpusStats | None = None,
    window_stats: WindowStats | None = None,
) -> dict[str, Any]:
    """Aggregate clusters into the JSONB snapshot shape persisted in Postgres.

    ``records``, ``labels``, and ``embeddings`` must be aligned: position ``i``
    in each refers to the same intent.

    All keyword arguments are optional so degraded runs still snapshot: without
    ``calls_by_session`` there are no journeys, switches, pivot, or overlaps;
    without descriptions there is no fit. Missing coverage inputs serialize as
    null meta fields, never as fabricated zeros.
    """
    if len(records) == 0:
        return empty_snapshot(distance_threshold, n_intents=0, corpus_stats=corpus_stats, window_stats=window_stats)
    assert len(records) == len(labels) == len(embeddings), (
        f"records ({len(records)}), labels ({len(labels)}), and embeddings ({len(embeddings)}) must be the same length"
    )

    flows = compute_cluster_flows(records, labels, calls_by_session or {})

    clusters_by_label: dict[int, list[int]] = defaultdict(list)
    for i, label in enumerate(labels.tolist()):
        clusters_by_label[int(label)].append(i)

    clusters: list[dict[str, Any]] = []
    for cluster_id, member_idx in clusters_by_label.items():
        members = [records[i] for i in member_idx]

        tool_counts: Counter[str] = Counter()
        error_counts: Counter[str] = Counter()
        for record in members:
            tool_counts.update(record.tool_counts)
            error_counts.update(record.error_counts)

        total_calls = sum(tool_counts.values())
        tool_distribution = [
            {
                "tool": tool,
                "count": count,
                "pct": _pct(count, total_calls),
                "errors": int(error_counts.get(tool, 0)),
                "error_rate_pct": _pct(error_counts.get(tool, 0), count),
            }
            for tool, count in tool_counts.most_common()
        ]

        medoid_pos = _medoid_index(embeddings, member_idx)
        sample_intents = [
            record.intent_text
            for record in sorted(members, key=lambda r: r.frequency, reverse=True)[:MAX_SAMPLE_INTENTS_PER_CLUSTER]
        ]

        flow = flows.get(cluster_id, {})
        # Distinct sessions when call data is available; the per-record sum
        # double-counts sessions whose calls span several member intents.
        session_count = (
            len(flow["session_ids"]) if "session_ids" in flow else int(sum(r.session_count for r in members))
        )

        clusters.append(
            {
                "id": cluster_id,
                "label": records[medoid_pos].intent_text,
                "intent_count": len(members),
                "session_count": session_count,
                "call_count": total_calls,
                "error_count": int(sum(error_counts.values())),
                "error_rate_pct": _pct(sum(error_counts.values()), total_calls),
                "tool_distribution": tool_distribution,
                "sample_intents": sample_intents,
                "routing_entropy": round(_routing_entropy(tool_counts), 3),
                "journey": flow.get("journey"),
                "switches": flow.get("switches", []),
                "self_retries": flow.get("self_retries", []),
            }
        )

    # Sort clusters by call volume desc so the UI shows the most impactful first.
    clusters.sort(key=lambda c: c["call_count"], reverse=True)

    # Persist only the highest-volume clusters; ``n_clusters`` keeps the full
    # count so the UI can say how many the run actually found.
    n_clusters_total = len(clusters)
    snapshot_clusters = clusters[:MAX_SNAPSHOT_CLUSTERS]

    fit = compute_description_fit(embeddings, labels, description_embeddings or {})
    if calls_by_session is not None:
        # The pivot totals read every cluster so the cap above never quietly
        # removes calls from a tool's counts, while its entries stay restricted
        # to the clusters this blob carries. Overlaps stay on the persisted
        # clusters because ``top_cluster_id`` has to resolve within the blob.
        tools, dropped_tools = compute_tool_pivot(
            clusters,
            calls_by_session,
            advertised_by_session or {},
            tool_descriptions or {},
            fit,
            snapshot_cluster_ids={cluster["id"] for cluster in snapshot_clusters},
        )
        tool_overlaps, dropped_pairs = compute_tool_overlaps(snapshot_clusters, calls_by_session)
    else:
        tools, dropped_tools, tool_overlaps, dropped_pairs = [], 0, [], 0

    described_tools = sum(1 for tool in tools if tool["description"])
    meta: dict[str, Any] = {
        "distance_threshold": distance_threshold,
        "embedding_model": EMBEDDING_MODEL,
        "n_intents": len(records),
        "n_clusters": n_clusters_total,
        "corpus": "per_call",
        "sampled_sessions": len(calls_by_session) if calls_by_session is not None else None,
        "window_sessions": window_stats.sessions if window_stats else None,
        "session_coverage_pct": (
            _pct(len(calls_by_session), window_stats.sessions)
            if calls_by_session is not None and window_stats
            else None
        ),
        "intent_coverage_pct": _pct(window_stats.calls_with_intent, window_stats.total_calls) if window_stats else None,
        "imputed_call_pct": _pct(corpus_stats.imputed_calls, corpus_stats.attributed_calls) if corpus_stats else None,
        "unattributed_call_pct": (
            _pct(corpus_stats.total_calls - corpus_stats.attributed_calls, corpus_stats.total_calls)
            if corpus_stats
            else None
        ),
        "corpus_call_coverage_pct": (
            _pct(corpus_stats.kept_calls, corpus_stats.attributed_calls) if corpus_stats else None
        ),
        "advertisement_coverage_pct": (
            _pct(len(set(advertised_by_session) & set(calls_by_session)), len(calls_by_session))
            if calls_by_session and advertised_by_session is not None
            else None
        ),
        "n_tools": len(tools),
        "dropped_tools": dropped_tools,
        "dropped_overlap_pairs": dropped_pairs,
        "description_coverage_pct": _pct(described_tools, len(tools)) if tools else None,
    }

    return {
        "version": SNAPSHOT_VERSION,
        "clusters": snapshot_clusters,
        "tools": tools,
        "tool_overlaps": tool_overlaps,
        "computed_with": meta,
    }


def empty_snapshot(
    distance_threshold: float,
    n_intents: int,
    corpus_stats: CorpusStats | None = None,
    window_stats: WindowStats | None = None,
) -> dict[str, Any]:
    """The no-clusters blob, keeping whatever coverage the run did establish.

    A window full of traffic that carried no attributable intent must not read
    the same as a window with no traffic at all: "0% of calls carried an intent"
    is the actionable message, all-null is a dead end.
    """
    return {
        "version": SNAPSHOT_VERSION,
        "clusters": [],
        "tools": [],
        "tool_overlaps": [],
        "computed_with": {
            "distance_threshold": distance_threshold,
            "embedding_model": EMBEDDING_MODEL,
            "n_intents": n_intents,
            "n_clusters": 0,
            "corpus": "per_call",
            "sampled_sessions": None,
            "window_sessions": window_stats.sessions if window_stats else None,
            "session_coverage_pct": None,
            "intent_coverage_pct": (
                _pct(window_stats.calls_with_intent, window_stats.total_calls) if window_stats else None
            ),
            "imputed_call_pct": None,
            "unattributed_call_pct": (
                _pct(corpus_stats.total_calls - corpus_stats.attributed_calls, corpus_stats.total_calls)
                if corpus_stats
                else None
            ),
            "corpus_call_coverage_pct": None,
            "advertisement_coverage_pct": None,
            "n_tools": 0,
            "dropped_tools": 0,
            "dropped_overlap_pairs": 0,
            "description_coverage_pct": None,
        },
    }
