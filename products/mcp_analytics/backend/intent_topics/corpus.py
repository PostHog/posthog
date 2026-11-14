"""Reads for the intent topics pipeline: distinct intents from events, and which ones already have vectors."""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import field
from datetime import UTC, datetime, timedelta

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.team.team import Team

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.mcp_analytics.backend.intent_hash import INTENT_HASH_HOGQL, INTENT_PROPERTY
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    EMBEDDING_RETENTION_DAYS,
    HASH_CHUNK_SIZE,
)


@frozen
class DistinctIntent:
    hash: str = field(repr=False)
    text: str = field(repr=False)
    calls: int
    source_min_timestamp: datetime


@frozen
class IntentSource:
    hash: str = field(repr=False)
    text: str = field(repr=False)
    calls: int
    source_min_timestamp: datetime


@frozen
class IntentQuery:
    sql: str
    parameters: dict[str, object]
    sources: Sequence[IntentSource] = field(repr=False)

    def execute(self, team: Team, *, settings: dict[str, object] | None = None) -> list:
        # These tables live on the main cluster, even when this team's events read from the events cluster.
        with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False)):
            return sync_execute(
                self.sql,
                self.parameters,
                team_id=team.pk,
                workload=Workload.OFFLINE,
                external_tables=[
                    {
                        "name": "mcp_intent_sources",
                        "structure": [
                            ("intent_hash", "String"),
                            ("text", "String"),
                            ("calls", "UInt64"),
                            ("source_min_timestamp", "DateTime64(6, 'UTC')"),
                        ],
                        "data": [(s.hash, s.text, s.calls, s.source_min_timestamp) for s in self.sources],
                    }
                ],
                settings={"timeout_overflow_mode": "throw", "read_overflow_mode": "throw", **(settings or {})},
            )


SOURCE_PAGE_SIZE = 5_000


def _source_time(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_LIVE_INTENTS_SQL = f"""
SELECT
    {INTENT_HASH_HOGQL} AS intent_hash,
    any(toString(properties.{INTENT_PROPERTY})) AS text,
    count() AS calls,
    min(timestamp) AS source_min_timestamp,
    sha256(concat(intent_hash, {{sample_salt}})) AS sort_key
FROM events
WHERE event = '$mcp_tool_call'
  AND timestamp >= {{since}}
  AND timestamp < {{until}}
  AND notEmpty(toString(properties.{INTENT_PROPERTY}))
GROUP BY intent_hash
HAVING (sort_key, intent_hash) > ({{after_key}}, {{after_hash}})
ORDER BY sort_key, intent_hash
LIMIT {{page_size}}
"""


def iter_live_intent_pages(
    team: Team, *, since: datetime, until: datetime, sample_salt: str = "", page_size: int = SOURCE_PAGE_SIZE
) -> Iterator[list[IntentSource]]:
    after_key = after_hash = ""
    while True:
        rows = (
            execute_hogql_query(
                query=parse_select(
                    _LIVE_INTENTS_SQL,
                    placeholders={
                        "since": ast.Constant(value=since),
                        "until": ast.Constant(value=until),
                        "sample_salt": ast.Constant(value=sample_salt),
                        "after_key": ast.Constant(value=after_key),
                        "after_hash": ast.Constant(value=after_hash),
                        "page_size": ast.Constant(value=page_size),
                    },
                ),
                team=team,
                workload=Workload.OFFLINE,
                settings=_COMPLETE_RESULTS_SETTINGS,
            ).results
            or []
        )
        if rows:
            yield [
                IntentSource(hash=r[0], text=r[1], calls=int(r[2]), source_min_timestamp=_source_time(r[3]))
                for r in rows
            ]
        if len(rows) < page_size:
            return
        after_key, after_hash = rows[-1][4], rows[-1][0]


def live_intent_embeddings_query(team: Team, sources: Sequence[IntentSource], *, as_of: datetime) -> IntentQuery:
    embedding_table = next(t for t in EMBEDDING_TABLES if t.model_name == EMBEDDING_MODEL).distributed_table_name()
    # Only vectors come from the cache: text, counts and provenance travel together from a fresh events read.
    sql = f"""
        SELECT
            source.intent_hash AS intent_hash,
            source.text AS text,
            source.calls AS calls,
            source.source_min_timestamp AS source_min_timestamp,
            argMax(e.embedding, tuple(e.timestamp, e.inserted_at)) AS embedding
        FROM {embedding_table} AS e
        GLOBAL INNER JOIN mcp_intent_sources AS source ON e.document_id = source.intent_hash
        WHERE e.team_id = %(intent_team_id)s
          AND e.product = %(intent_product)s
          AND e.document_type = %(intent_document_type)s
          AND e.timestamp >= %(embedding_since)s
          AND e.timestamp < %(embedding_until)s
        GROUP BY source.intent_hash, source.text, source.calls, source.source_min_timestamp
    """
    return IntentQuery(
        sql=sql,
        parameters={
            "intent_team_id": team.pk,
            "intent_product": EMBEDDING_PRODUCT,
            "intent_document_type": EMBEDDING_DOCUMENT_TYPE,
            "embedding_since": as_of - timedelta(days=EMBEDDING_RETENTION_DAYS),
            "embedding_until": as_of,
        },
        sources=sources,
    )


# Ordered by hash so pages follow a stable key. Only the intent text leaves the events table: a copy of any
# other property would be readable by members that property's restrictions exclude.
_DISTINCT_INTENTS_SQL = f"""
SELECT
    {INTENT_HASH_HOGQL} AS intent_hash,
    any(toString(properties.{INTENT_PROPERTY})) AS text,
    count() AS calls,
    min(timestamp) AS source_min_timestamp
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


# A query that hits a time or read limit must fail rather than return a partial page, which would read as the last one.
_COMPLETE_RESULTS_SETTINGS = HogQLGlobalSettings(timeout_overflow_mode="throw", read_overflow_mode="throw")


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
        rows = (
            execute_hogql_query(
                query=query, team=team, workload=Workload.OFFLINE, settings=_COMPLETE_RESULTS_SETTINGS
            ).results
            or []
        )
        if rows:
            yield [
                DistinctIntent(hash=row[0], text=row[1], calls=int(row[2]), source_min_timestamp=_source_time(row[3]))
                for row in rows
            ]
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
        response = execute_hogql_query(
            query=query,
            team=team,
            workload=Workload.OFFLINE,
            modifiers=HogQLQueryModifiers(useNewEventsSchema=False),
        )
        seen.update(row[0] for row in response.results)
    return seen
