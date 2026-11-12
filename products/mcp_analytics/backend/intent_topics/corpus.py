"""Reads for the intent topics pipeline: distinct intents from events, and which ones already have vectors."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team

from products.mcp_analytics.backend.hogql_queries.base import EFFECTIVE_TOOL_SQL
from products.mcp_analytics.backend.intent_hash import INTENT_HASH_HOGQL, INTENT_PROPERTY
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    EMBEDDING_RETENTION_DAYS,
    HASH_CHUNK_SIZE,
    MAX_NEW_INTENTS_PER_SYNC,
)


@dataclass(frozen=True)
class DistinctIntent:
    hash: str
    text: str
    calls: int
    top_tool: str
    intent_source: str


_DISTINCT_INTENTS_SQL = f"""
SELECT
    {INTENT_HASH_HOGQL} AS intent_hash,
    any(toString(properties.{INTENT_PROPERTY})) AS text,
    count() AS calls,
    topK(1)({EFFECTIVE_TOOL_SQL}) AS top_tools,
    any(toString(properties.$mcp_intent_source)) AS intent_source
FROM events
WHERE event = '$mcp_tool_call'
  AND timestamp >= {{since}}
  AND timestamp < {{until}}
  AND notEmpty(toString(properties.{INTENT_PROPERTY}))
GROUP BY intent_hash
ORDER BY calls DESC, intent_hash
LIMIT {{limit}}
"""


def fetch_distinct_intents(
    team: Team, *, since: datetime, until: datetime, limit: int = MAX_NEW_INTENTS_PER_SYNC
) -> list[DistinctIntent]:
    """Distinct intent texts called in [since, until), most called first."""
    query = parse_select(
        _DISTINCT_INTENTS_SQL,
        placeholders={
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=until),
            "limit": ast.Constant(value=limit),
        },
    )
    response = execute_hogql_query(query=query, team=team)
    return [
        DistinctIntent(
            hash=row[0],
            text=row[1],
            calls=int(row[2]),
            top_tool=(row[3] or [""])[0] or "",
            intent_source=row[4] or "",
        )
        for row in response.results
    ]


_SEEN_HASHES_SQL = """
SELECT DISTINCT document_id
FROM document_embeddings
WHERE model_name = {model}
  AND product = {product}
  AND document_type = {document_type}
  AND timestamp >= {since}
  AND document_id IN {hashes}
"""


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def fetch_seen_hashes(team: Team, hashes: Sequence[str], *, now: datetime) -> set[str]:
    """Which of ``hashes`` already have a vector for this team inside the embedding retention window."""
    if not hashes:
        return set()
    since = now - timedelta(days=EMBEDDING_RETENTION_DAYS)
    seen: set[str] = set()
    for chunk in _chunks(list(hashes), HASH_CHUNK_SIZE):
        query = parse_select(
            _SEEN_HASHES_SQL,
            placeholders={
                "model": ast.Constant(value=EMBEDDING_MODEL),
                "product": ast.Constant(value=EMBEDDING_PRODUCT),
                "document_type": ast.Constant(value=EMBEDDING_DOCUMENT_TYPE),
                "since": ast.Constant(value=since),
                "hashes": ast.Constant(value=list(chunk)),
            },
        )
        response = execute_hogql_query(query=query, team=team)
        seen.update(row[0] for row in response.results)
    return seen
