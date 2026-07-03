"""Intent clustering pipeline for MCP analytics.

Four pure functions, each independently testable, that together build a cluster
snapshot of MCP intents. The Celery task in ``tasks.py`` orchestrates them and
persists the result.

Why pure functions: the algorithm is the riskiest part of this feature. Keeping
each stage as a pure function over numpy arrays / dataclasses makes the
algorithm validatable without touching ClickHouse, Postgres, or the embedding
service.

Intent sources: the corpus is built from the ``$mcp_intent`` recorded on tool-call
events (the first intent of each session, sampled from ClickHouse), overlaid with
the LLM-generated session summaries from ``posthog_mcp_session`` where those exist.
Event intents give scale without any LLM dependency; summaries, generated on
demand, win per session because they condense the whole session's intents.
"""

import math
import asyncio
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.utils import timezone

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import EmbeddingResponse, async_generate_embedding
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.models import MCPIntentEmbeddingCache, MCPSession

# Constants
EMBEDDING_MODEL = "text-embedding-3-small-1536"
EMBEDDING_PREFIX = "User intent: "
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_TOP_N_INTENTS = 500
DEFAULT_DISTANCE_THRESHOLD = 0.2
MAX_SAMPLE_INTENTS_PER_CLUSTER = 3

# Placeholder previously written by the (now-removed) summariser job for sessions with no
# recordable tool-call intents. Still filtered out of the corpus so it doesn't form a
# meaningless pseudo-cluster of "empty" sessions.
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
    """One unique intent text, with the tool-call statistics observed for it."""

    intent_text: str
    frequency: int
    session_count: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)


# Intent corpus -----------------------------------------------------------

# Bound on sessions sampled from ClickHouse for the corpus. Keeps the IN-tuple
# in the two per-session queries below at a sane size; with
# DEFAULT_TOP_N_INTENTS=500 a larger sample only adds long-tail singletons.
MAX_CORPUS_SESSIONS = 2000

# Event-sourced intents are free text written by the calling agent — clip them
# so one oversized value can't blow up embedding requests (the worker's model
# has a token ceiling) or bloat the snapshot blob. Real intents are one or two
# sentences; anything past this length adds no clustering signal.
MAX_INTENT_TEXT_LENGTH = 1000

# First (chronological) $mcp_intent per session — the agent's opening task
# statement, used as the session's representative intent unless an on-demand
# LLM summary exists in Postgres. Ordering by cityHash64(session_id) is a
# deterministic pseudo-random sample: unbiased across the window (newest-first
# would collapse the corpus to the last few hours at production volume) and
# stable across reruns, so repeat runs re-hit the embedding cache.
# NB: `$session_id` is the materialised events column ('' when absent), NOT the
# `properties.` accessor — same rationale as logic.py's session SQL.
_SESSION_FIRST_INTENT_SQL = """
SELECT
    $session_id AS session_id,
    argMin(toString(properties.$mcp_intent), timestamp) AS first_intent
FROM events
WHERE event = {event}
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
    AND $session_id != ''
    AND coalesce(toString(properties.$mcp_intent), '') != ''
GROUP BY session_id
ORDER BY cityHash64(session_id)
LIMIT {max_sessions}
"""

# Per-session tool stats: for each session in the corpus, what tools were
# called and how often. Joined in Python with the session→intent map so the
# same intent string can aggregate across sessions.
# TODO(intent-routing): chaining is by $session_id today; swap to
# $mcp_session_id once tool calls carry it consistently.
_SESSION_TOOL_STATS_SQL = """
SELECT
    $session_id AS session_id,
    toString(properties.$mcp_tool_name) AS tool_name,
    countIf(toString(properties.$mcp_is_error) NOT IN ('true', '1')) AS success_count,
    countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS error_count
FROM events
WHERE event = {event}
    AND $session_id IN {session_ids}
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
GROUP BY session_id, tool_name
"""

# Per-session ordered tool sequence + whether any call errored. arrayMap +
# arraySort on (timestamp, tool) tuples preserves call order.
_SESSION_JOURNEY_SQL = """
SELECT
    $session_id AS session_id,
    arrayMap(
        x -> x.2,
        arraySort(
            x -> x.1,
            groupArray(tuple(timestamp, toString(properties.$mcp_tool_name)))
        )
    ) AS tool_sequence,
    countIf(toString(properties.$mcp_is_error) IN ('true', '1')) > 0 AS had_error
FROM events
WHERE event = {event}
    AND $session_id IN {session_ids}
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
GROUP BY session_id
"""


def fetch_intent_corpus(
    team: Team,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    top_n: int = DEFAULT_TOP_N_INTENTS,
) -> tuple[list[IntentRecord], dict[str, str]]:
    """Return ``(records, intent_by_session)`` for clustering.

    Each session's intent text is the first ``$mcp_intent`` it recorded (sampled
    from ClickHouse, capped at ``MAX_CORPUS_SESSIONS``), overridden by the
    on-demand LLM summary from posthog_mcp_session where one exists — the
    summary condenses the whole session, so it wins. Tool stats come from
    ClickHouse $mcp_tool_call events joined by session_id. Same intent string
    repeated across sessions aggregates.

    ``intent_by_session`` is exposed so callers can later join session-level
    data (e.g. journey aggregation) back to the cluster a session belongs to.

    ``lookback_days`` bounds both stores to the same window: event queries
    filter by timestamp, and session intent rows are filtered by ``created_at``
    (when the intent was generated, since intents are produced on demand).
    """
    intent_query = parse_select(
        _SESSION_FIRST_INTENT_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "lookback_days": ast.Constant(value=lookback_days),
            "max_sessions": ast.Constant(value=MAX_CORPUS_SESSIONS),
        },
    )
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        intent_response = execute_hogql_query(query=intent_query, team=team)

    # Map session_id -> intent_text. Skip the summariser's "no intents
    # recorded" placeholder — clustering it produces a meaningless
    # pseudo-cluster of sessions with nothing in common except that their
    # tool calls had no $mcp_intent property.
    intent_by_session: dict[str, str] = {}
    for row in intent_response.results or []:
        session_id = str(row[0] or "")
        text = str(row[1] or "").strip()[:MAX_INTENT_TEXT_LENGTH]
        if not session_id or not text or text == NO_INTENT_RECORDED_FALLBACK:
            continue
        intent_by_session[session_id] = text

    # Overlay LLM-generated session summaries, and include summarised sessions
    # the event sample missed (e.g. generated for a session whose events sit
    # just outside the sampled set).
    window_start = timezone.now() - timedelta(days=lookback_days)
    session_rows = MCPSession.objects.filter(team=team, created_at__gte=window_start).values_list(
        "session_id", "intent"
    )
    for session_id, intent_text in session_rows:
        text = (intent_text or "").strip()[:MAX_INTENT_TEXT_LENGTH]
        if not session_id or not text or text == NO_INTENT_RECORDED_FALLBACK:
            continue
        intent_by_session[session_id] = text

    if not intent_by_session:
        return [], {}

    session_ids = list(intent_by_session.keys())
    query = parse_select(
        _SESSION_TOOL_STATS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "session_ids": ast.Tuple(exprs=[ast.Constant(value=sid) for sid in session_ids]),
            "lookback_days": ast.Constant(value=lookback_days),
        },
    )
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(query=query, team=team)

    # Aggregate per intent_text across all sessions that share it.
    rollup: dict[str, dict[str, Any]] = {}
    # Seed rollup with every intent we saw in Postgres so intents with no
    # tool calls yet still surface (as a singleton, zero-call cluster).
    session_count: Counter[str] = Counter()
    for intent_text in intent_by_session.values():
        session_count[intent_text] += 1
        rollup.setdefault(intent_text, {"tool_counts": {}, "error_counts": {}})

    for row in response.results or []:
        session_id = row[0] or ""
        tool_name = row[1] or ""
        success = int(row[2] or 0)
        errors = int(row[3] or 0)
        intent_text = intent_by_session.get(session_id)
        if not intent_text or not tool_name:
            continue
        bucket = rollup[intent_text]
        bucket["tool_counts"][tool_name] = bucket["tool_counts"].get(tool_name, 0) + success + errors
        if errors:
            bucket["error_counts"][tool_name] = bucket["error_counts"].get(tool_name, 0) + errors

    records: list[IntentRecord] = []
    for text, data in rollup.items():
        total_calls = sum(data["tool_counts"].values())
        # Use session count as the ranking signal when no tool calls exist yet;
        # otherwise total calls dominate.
        frequency = total_calls or session_count[text]
        records.append(
            IntentRecord(
                intent_text=text,
                frequency=frequency,
                session_count=session_count[text],
                tool_counts=data["tool_counts"],
                error_counts=data["error_counts"],
            )
        )

    records.sort(key=lambda r: r.frequency, reverse=True)
    return records[:top_n], intent_by_session


# Journeys ----------------------------------------------------------------


def fetch_session_journeys(
    team: Team,
    session_ids: list[str],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, dict[str, Any]]:
    """Return ``{session_id: {tool_sequence: [...], had_error: bool}}``.

    Tool calls are sorted by timestamp so the sequence reflects the order
    the agent invoked them.
    """
    if not session_ids:
        return {}
    query = parse_select(
        _SESSION_JOURNEY_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "session_ids": ast.Tuple(exprs=[ast.Constant(value=sid) for sid in session_ids]),
            "lookback_days": ast.Constant(value=lookback_days),
        },
    )
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(query=query, team=team)

    out: dict[str, dict[str, Any]] = {}
    for row in response.results or []:
        session_id = row[0] or ""
        tool_sequence = list(row[1] or [])
        had_error = bool(row[2])
        if not session_id:
            continue
        out[session_id] = {"tool_sequence": tool_sequence, "had_error": had_error}
    return out


def aggregate_journeys_per_cluster(
    records: list[IntentRecord],
    labels: np.ndarray,
    session_journeys: dict[str, dict[str, Any]],
    intent_to_sessions: dict[str, list[str]],
) -> dict[int, dict[str, Any]]:
    """For each cluster id, build a Sankey-shaped journey aggregation.

    Walks each session in each cluster, takes the first ``JOURNEY_DEPTH``
    ordered tool calls (padded with ``None`` for shorter sessions), pairs
    them with an ``error``/``completed`` outcome, and counts unique paths.
    Returns a per-cluster dict with ``paths`` (top N), ``total_sessions``,
    and ``leak`` (highest-volume non-completed path).
    """
    journeys_by_cluster: dict[int, Counter[tuple[tuple[str | None, ...], str]]] = defaultdict(Counter)

    for i, record in enumerate(records):
        cluster_id = int(labels[i])
        for session_id in intent_to_sessions.get(record.intent_text, []):
            journey = session_journeys.get(session_id)
            if not journey:
                continue
            raw_sequence = journey["tool_sequence"][:JOURNEY_DEPTH]
            padded: list[str | None] = [str(t) for t in raw_sequence] + [None] * (JOURNEY_DEPTH - len(raw_sequence))
            outcome = "error" if journey.get("had_error") else "completed"
            journeys_by_cluster[cluster_id][(tuple(padded), outcome)] += 1

    result: dict[int, dict[str, Any]] = {}
    for cluster_id, path_counts in journeys_by_cluster.items():
        ranked = path_counts.most_common()
        total_sessions = sum(path_counts.values())
        leak_path: dict[str, Any] | None = None
        for (steps, outcome), count in ranked:
            if outcome != "completed":
                leak_path = {"steps": list(steps), "outcome": outcome, "count": count}
                break
        result[cluster_id] = {
            "paths": [
                {"steps": list(steps), "outcome": outcome, "count": count}
                for (steps, outcome), count in ranked[:MAX_JOURNEY_PATHS_PER_CLUSTER]
            ],
            "total_sessions": total_sessions,
            "leak": leak_path,
        }
    return result


# Embeddings --------------------------------------------------------------


def _content_hash(text: str) -> str:
    """SHA-256 of the prefixed text — what we actually embed."""
    return hashlib.sha256((EMBEDDING_PREFIX + text).encode("utf-8")).hexdigest()


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


async def _embed_one_with_cache(
    team: Team,
    text: str,
    content_hash: str,
    semaphore: asyncio.Semaphore,
    cached: dict[str, np.ndarray],
) -> np.ndarray | None:
    """Return the embedding for ``text``, hitting the cache when possible.

    Concurrency is bounded by ``semaphore``; cache reads come pre-loaded in
    ``cached`` so the hot path is a dict lookup. Misses go through
    ``async_generate_embedding`` and write back on success.
    """
    hit = cached.get(content_hash)
    if hit is not None:
        return hit
    async with semaphore:
        try:
            response: EmbeddingResponse = await async_generate_embedding(
                team, EMBEDDING_PREFIX + text, model=EMBEDDING_MODEL
            )
        except Exception:
            return None
    try:
        await _persist_embedding(team, content_hash, EMBEDDING_MODEL, response.embedding)
    except Exception:
        # A concurrent insert for the same (team, hash, model) is fine —
        # the unique constraint guarantees the row exists. Don't fail the
        # whole batch over a race.
        pass
    return np.asarray(response.embedding, dtype=np.float32)


async def embed_intents_async(team: Team, texts: list[str]) -> tuple[np.ndarray, list[int]]:
    """Embed a list of intent texts concurrently, with a per-team cache.

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

    hashes = [_content_hash(t) for t in texts]
    cached = await _load_cached_embeddings(team, hashes, EMBEDDING_MODEL)
    semaphore = asyncio.Semaphore(EMBED_CONCURRENCY)

    results = await asyncio.gather(
        *[
            _embed_one_with_cache(team, text, content_hash, semaphore, cached)
            for text, content_hash in zip(texts, hashes)
        ]
    )

    vectors: list[np.ndarray] = []
    valid_indices: list[int] = []
    for i, vector in enumerate(results):
        if vector is None:
            continue
        vectors.append(vector)
        valid_indices.append(i)

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


def build_snapshot(
    records: list[IntentRecord],
    labels: np.ndarray,
    embeddings: np.ndarray,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    journeys_by_cluster: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate clusters into the JSONB snapshot shape persisted in Postgres.

    ``records``, ``labels``, and ``embeddings`` must be aligned: position ``i``
    in each refers to the same intent.

    ``journeys_by_cluster`` is the output of ``aggregate_journeys_per_cluster``
    keyed by cluster id. Optional; clusters without an entry get a null journey.
    """
    if len(records) == 0:
        return _empty_snapshot(distance_threshold, n_intents=0)
    assert len(records) == len(labels) == len(embeddings), (
        f"records ({len(records)}), labels ({len(labels)}), and embeddings ({len(embeddings)}) must be the same length"
    )

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
                "pct": round(100.0 * count / total_calls, 1) if total_calls else 0.0,
                "errors": int(error_counts.get(tool, 0)),
                "error_rate_pct": round(100.0 * error_counts.get(tool, 0) / count, 1) if count else 0.0,
            }
            for tool, count in tool_counts.most_common()
        ]

        medoid_pos = _medoid_index(embeddings, member_idx)
        sample_intents = [
            record.intent_text
            for record in sorted(members, key=lambda r: r.frequency, reverse=True)[:MAX_SAMPLE_INTENTS_PER_CLUSTER]
        ]

        clusters.append(
            {
                "id": cluster_id,
                "label": records[medoid_pos].intent_text,
                "intent_count": len(members),
                "session_count": int(sum(r.session_count for r in members)),
                "call_count": total_calls,
                "error_count": int(sum(error_counts.values())),
                "error_rate_pct": round(100.0 * sum(error_counts.values()) / total_calls, 1) if total_calls else 0.0,
                "tool_distribution": tool_distribution,
                "sample_intents": sample_intents,
                "routing_entropy": round(_routing_entropy(tool_counts), 3),
                "journey": (journeys_by_cluster or {}).get(cluster_id),
            }
        )

    # Sort clusters by call volume desc so the UI shows the most impactful first.
    clusters.sort(key=lambda c: c["call_count"], reverse=True)

    return {
        "clusters": clusters,
        "computed_with": {
            "distance_threshold": distance_threshold,
            "embedding_model": EMBEDDING_MODEL,
            "n_intents": len(records),
            "n_clusters": len(clusters),
        },
    }


def _empty_snapshot(distance_threshold: float, n_intents: int) -> dict[str, Any]:
    return {
        "clusters": [],
        "computed_with": {
            "distance_threshold": distance_threshold,
            "embedding_model": EMBEDDING_MODEL,
            "n_intents": n_intents,
            "n_clusters": 0,
        },
    }
