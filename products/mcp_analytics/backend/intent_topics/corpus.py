"""Reads for the intent topics pipeline: distinct intents from events, and which ones already have vectors."""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.models.team.team import Team

from products.mcp_analytics.backend.intent_hash import INTENT_HASH_HOGQL, INTENT_PROPERTY
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    EMBEDDING_RETENTION_DAYS,
    HASH_CHUNK_SIZE,
)


@dataclass(frozen=True)
class DistinctIntent:
    hash: str
    text: str
    calls: int


# Ordered by hash so pages follow a stable key. Only the intent text leaves the events table: a copy of any
# other property would be readable by members that property's restrictions exclude.
_DISTINCT_INTENTS_SQL = f"""
SELECT
    {INTENT_HASH_HOGQL} AS intent_hash,
    any(toString(properties.{INTENT_PROPERTY})) AS text,
    count() AS calls
FROM events
WHERE event = '$mcp_tool_call'
  AND timestamp >= {{since}}
  AND timestamp < {{until}}
  AND notEmpty(toString(properties.{INTENT_PROPERTY}))
GROUP BY intent_hash
HAVING intent_hash > {{after}}
ORDER BY intent_hash
LIMIT {{page_size}}
"""


def iter_distinct_intent_pages(
    team: Team, *, since: datetime, until: datetime, page_size: int = MAX_SELECT_RETURNED_ROWS
) -> Iterator[list[DistinctIntent]]:
    """Every distinct intent text called in [since, until), in pages ordered by hash.

    A single HogQL query returns at most MAX_SELECT_RETURNED_ROWS rows, so each page starts after the
    last hash of the page before it.
    """
    after = ""
    while True:
        query = parse_select(
            _DISTINCT_INTENTS_SQL,
            placeholders={
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
                "after": ast.Constant(value=after),
                "page_size": ast.Constant(value=page_size),
            },
        )
        rows = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE).results or []
        if rows:
            yield [DistinctIntent(hash=row[0], text=row[1], calls=int(row[2])) for row in rows]
        if len(rows) < page_size:
            return
        after = rows[-1][0]


_SEEN_HASHES_SQL = """
SELECT DISTINCT document_id
FROM document_embeddings
WHERE model_name = {model}
  AND product = {product}
  AND document_type = {document_type}
  AND timestamp >= {since}
  AND document_id IN {hashes}
LIMIT {limit}
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
                "limit": ast.Constant(value=len(chunk)),
            },
        )
        response = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE)
        seen.update(row[0] for row in response.results)
    return seen
