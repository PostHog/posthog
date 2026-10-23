"""Reads for the intent topics pipeline: distinct intents from events, and which ones already have vectors."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.models.team.team import Team

from products.mcp_analytics.backend.hogql_queries.base import CONVERSATION_ID_SQL, EFFECTIVE_TOOL_SQL
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
LIMIT {{page_size}}
OFFSET {{offset}}
"""


def fetch_distinct_intents(
    team: Team,
    *,
    since: datetime,
    until: datetime,
    limit: int = MAX_NEW_INTENTS_PER_SYNC,
    page_size: int = MAX_SELECT_RETURNED_ROWS,
) -> list[DistinctIntent]:
    """Distinct intent texts called in [since, until), most called first.

    A single HogQL query returns at most MAX_SELECT_RETURNED_ROWS rows, so larger windows are read in
    pages ordered by a stable key.
    """
    intents: list[DistinctIntent] = []
    while len(intents) < limit:
        size = min(page_size, limit - len(intents))
        query = parse_select(
            _DISTINCT_INTENTS_SQL,
            placeholders={
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
                "page_size": ast.Constant(value=size),
                "offset": ast.Constant(value=len(intents)),
            },
        )
        rows = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE).results or []
        intents.extend(
            DistinctIntent(
                hash=row[0],
                text=row[1],
                calls=int(row[2]),
                top_tool=(row[3] or [""])[0] or "",
                intent_source=row[4] or "",
            )
            for row in rows
        )
        if len(rows) < size:
            break
    return intents


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


@dataclass(frozen=True)
class HourlyCalls:
    hour: datetime
    hash: str
    tool: str
    calls: int
    # cityHash64 of each distinct conversation id, so the rollups can count conversations without double counting.
    conversations: tuple[int, ...]


_HOURLY_CALLS_SQL = f"""
SELECT
    toStartOfHour(timestamp) AS hour,
    {INTENT_HASH_HOGQL} AS intent_hash,
    {EFFECTIVE_TOOL_SQL} AS tool,
    count() AS calls,
    arraySort(groupUniqArray(cityHash64({CONVERSATION_ID_SQL}))) AS conversations
FROM events
WHERE event = '$mcp_tool_call'
  AND timestamp >= {{since}}
  AND timestamp < {{until}}
  AND notEmpty(toString(properties.{INTENT_PROPERTY}))
GROUP BY hour, intent_hash, tool
ORDER BY hour, intent_hash, tool
LIMIT {{page_size}}
OFFSET {{offset}}
"""


def _start_of_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def fetch_hourly_calls(
    team: Team, *, since: datetime, until: datetime, page_size: int = MAX_SELECT_RETURNED_ROWS
) -> list[HourlyCalls]:
    """Calls and conversations per (hour, intent text, tool) for the complete hours that overlap [since, until).

    The rollup replaces a whole hourly bucket on every write, so a partial hour would overwrite a complete
    one. The window therefore widens to the start of the first hour and stops at the start of the last.
    """
    since, until = _start_of_hour(since), _start_of_hour(until)
    rows: list[HourlyCalls] = []
    while since < until:
        query = parse_select(
            _HOURLY_CALLS_SQL,
            placeholders={
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
                "page_size": ast.Constant(value=page_size),
                "offset": ast.Constant(value=len(rows)),
            },
        )
        # Hour keys must be UTC: the daily rebuild groups them into days, and project-local hours break
        # at fractional offsets such as +05:30.
        page = (
            execute_hogql_query(
                query=query,
                team=team,
                workload=Workload.OFFLINE,
                modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
            ).results
            or []
        )
        rows.extend(
            HourlyCalls(hour=row[0], hash=row[1], tool=row[2] or "", calls=int(row[3]), conversations=tuple(row[4]))
            for row in page
        )
        if len(page) < page_size:
            break
    return rows
