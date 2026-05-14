"""Intent clustering pipeline for MCP analytics.

Four pure functions, each independently testable, that together build a cluster
snapshot of MCP intents. The Celery task in ``tasks.py`` orchestrates them and
persists the result.

Why pure functions: the algorithm is the riskiest part of this feature. Keeping
each stage as a pure function over numpy arrays / dataclasses makes the
algorithm validatable without touching ClickHouse, Postgres, or the embedding
service.

Why ``$mcp_intent`` per-event for v1: a session-level summarised-intent table is
being built in parallel. ``fetch_intent_corpus`` is the only function that needs
to change when that table lands — swap its body to read from the new source.
"""

import math
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import EmbeddingResponse, async_generate_embedding
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team

from products.mcp_analytics.backend.models import MCPSession

# Constants
EMBEDDING_MODEL = "text-embedding-3-small-1536"
EMBEDDING_PREFIX = "User intent: "
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_TOP_N_INTENTS = 500
DEFAULT_DISTANCE_THRESHOLD = 0.2
MAX_SAMPLE_INTENTS_PER_CLUSTER = 3


@dataclass(frozen=True)
class IntentRecord:
    """One unique intent text, with the tool-call statistics observed for it."""

    intent_text: str
    frequency: int
    tool_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)


# Intent corpus -----------------------------------------------------------

# Per-session tool stats: for each session_id we know about in Postgres, what
# tools were called and how often. Joined in Python with the session→intent
# map from Postgres so the same intent string can aggregate across sessions.
# TODO(mcp-sessions): when the parallel-team posthog_mcp_session table ships,
# change MCPSession.objects.filter(...) below to point at the real model.
# TODO(intent-routing): chaining is by $session_id today; swap to
# $conversation_id once tool calls carry it.
_SESSION_TOOL_STATS_SQL = """
SELECT
    properties.$session_id AS session_id,
    toString(properties.$mcp_tool_name) AS tool_name,
    countIf(toString(properties.$mcp_is_error) NOT IN ('true', '1')) AS success_count,
    countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS error_count
FROM events
WHERE event = {event}
    AND properties.$session_id IN {session_ids}
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND timestamp >= now() - INTERVAL {lookback_days} DAY
GROUP BY session_id, tool_name
"""


def fetch_intent_corpus(
    team: Team,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    top_n: int = DEFAULT_TOP_N_INTENTS,
) -> list[IntentRecord]:
    """Return the top-N most frequent distinct intents with their tool stats.

    The intent text comes from posthog_mcp_session (Postgres), one row per
    MCP session. Tool stats come from ClickHouse mcp_tool_call events joined
    by session_id. Same intent string repeated across sessions aggregates.
    """
    session_rows = list(MCPSession.objects.filter(team=team).values_list("session_id", "intent"))
    if not session_rows:
        return []

    # Map session_id -> intent_text (last write wins per session).
    intent_by_session: dict[str, str] = {}
    for session_id, intent_text in session_rows:
        text = (intent_text or "").strip()
        if not session_id or not text:
            continue
        intent_by_session[session_id] = text

    if not intent_by_session:
        return []

    session_ids = list(intent_by_session.keys())
    query = parse_select(
        _SESSION_TOOL_STATS_SQL,
        placeholders={
            "event": ast.Constant(value="mcp_tool_call"),
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
                tool_counts=data["tool_counts"],
                error_counts=data["error_counts"],
            )
        )

    records.sort(key=lambda r: r.frequency, reverse=True)
    return records[:top_n]


# Embeddings --------------------------------------------------------------


async def _embed_one(team: Team, text: str) -> EmbeddingResponse | None:
    try:
        return await async_generate_embedding(team, EMBEDDING_PREFIX + text, model=EMBEDDING_MODEL)
    except Exception:
        return None


async def embed_intents_async(team: Team, texts: list[str]) -> tuple[np.ndarray, list[int]]:
    """Embed a list of intent texts concurrently.

    Returns (embeddings, valid_indices) where ``valid_indices`` are the indices
    into ``texts`` for which embedding succeeded. Skipped indices have no row
    in the returned matrix. Callers must align downstream data structures with
    ``valid_indices``.
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32), []

    responses = await asyncio.gather(*[_embed_one(team, t) for t in texts])

    vectors: list[list[float]] = []
    valid_indices: list[int] = []
    for i, response in enumerate(responses):
        if response is None:
            continue
        vectors.append(response.embedding)
        valid_indices.append(i)

    if not vectors:
        return np.zeros((0, 0), dtype=np.float32), []

    return np.asarray(vectors, dtype=np.float32), valid_indices


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
) -> dict[str, Any]:
    """Aggregate clusters into the JSONB snapshot shape persisted in Postgres.

    ``records``, ``labels``, and ``embeddings`` must be aligned: position ``i``
    in each refers to the same intent.
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
                "call_count": total_calls,
                "error_count": int(sum(error_counts.values())),
                "error_rate_pct": round(100.0 * sum(error_counts.values()) / total_calls, 1) if total_calls else 0.0,
                "tool_distribution": tool_distribution,
                "sample_intents": sample_intents,
                "routing_entropy": round(_routing_entropy(tool_counts), 3),
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
