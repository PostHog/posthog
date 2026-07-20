import json
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Union

import structlog
import temporalio

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import DocumentKey, async_get_recently_seen_documents, emit_embedding_request
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.signal_metadata import EMBEDDING_MODEL
from products.signals.backend.temporal import metrics
from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry
from products.signals.backend.temporal.types import SignalCandidate, SignalData, SignalTypeExample

logger = structlog.get_logger(__name__)


WAIT_POLL_INTERVAL_SECONDS = 10

# Every signal document is emitted under this key triple — the recently-seen lookup in
# wait_for_signal_in_clickhouse_activity relies on exact key equality with the emit sites.
SIGNAL_DOCUMENT_PRODUCT = "signals"
SIGNAL_DOCUMENT_TYPE = "signal"
SIGNAL_DOCUMENT_RENDERING = "plain"

# How often to run the ClickHouse confirmation query when the recently-seen store hasn't
# confirmed the emission — the store is best-effort (writes never block ingestion, and the
# in-memory backend is per-pod), so a negative answer can't gate ClickHouse polling forever.
CH_CONFIRM_EVERY_N_ATTEMPTS = 3

# Slack when comparing the store's emitted_at against the signal's expected timestamp, to
# absorb sub-second precision loss in serialization round-trips.
RECENTLY_SEEN_TIMESTAMP_TOLERANCE = timedelta(seconds=2)


def _ensure_tz_aware(value: Union[datetime, str]) -> datetime:
    """Coerce a ClickHouse timestamp (usually a datetime, occasionally a string) to a tz-aware datetime."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


# ---------------------------------------------------------------------------
# Shared query builders
# ---------------------------------------------------------------------------


def _deduped_signals_subquery(
    *, include_embedding: bool = False, extra_where: str | None = None, candidate_document_filter: str | None = None
) -> str:
    """Build the shared signal dedup subquery with an optional extra document_embeddings filter.

    `candidate_document_filter` bounds the dedup to documents that ever matched the filter, via a
    `document_id IN (SELECT DISTINCT ... WHERE <filter>)` prefilter — so the argMax aggregation runs
    over that slice instead of the team's whole signal history (its memory otherwise scales with the
    team's total signal count). Unlike `extra_where`, the filter selects candidate documents but does
    NOT restrict which versions feed the argMax, so "latest version wins" is preserved and the caller's
    own outer filter stays authoritative. Use it for re-groupable fields like `report_id`; use
    `extra_where` only for fields that are stable across a document's versions (e.g. `source_id`).

    Raises ValueError if both extra_where and candidate_document_filter are supplied — they are
    mutually exclusive (the extra_where branch returns early and silently drops candidate_document_filter).
    """
    if extra_where and candidate_document_filter:
        raise ValueError("_deduped_signals_subquery: extra_where and candidate_document_filter are mutually exclusive")
    selected_columns = [
        "document_id",
        "argMax(content, inserted_at) as content",
        "argMax(metadata, inserted_at) as metadata",
    ]
    if include_embedding:
        selected_columns.append("argMax(embedding, inserted_at) as embedding")
    selected_columns.append("argMax(timestamp, inserted_at) as timestamp")
    selected_columns_sql = ",\n            ".join(selected_columns)

    if extra_where:
        # `extra_where` filters on the raw `metadata` JSON, but this SELECT also exposes
        # `metadata` as an `argMax(...)` alias. HogQL resolves the name in WHERE to that
        # aggregate alias and rejects the query ("aggregate function ... found in WHERE"),
        # so any caller that filtered on `metadata` silently failed. Apply the predicate in
        # a non-aggregating inner scan so it binds to the raw column, then dedupe in the
        # outer aggregate. Pushing the filter down here (vs. the caller's outer query) keeps
        # the dedup scan bounded to the matching rows.
        raw_columns = ["document_id", "content", "metadata"]
        if include_embedding:
            raw_columns.append("embedding")
        raw_columns.extend(["inserted_at", "timestamp"])
        raw_columns_sql = ",\n                ".join(raw_columns)
        return f"""
        SELECT
            {selected_columns_sql}
        FROM (
            SELECT
                {raw_columns_sql}
            FROM document_embeddings
            WHERE model_name = {{model_name}}
              AND product = 'signals'
              AND document_type = 'signal'
              AND {extra_where}
        )
        GROUP BY document_id
    """

    candidate_bound = ""
    if candidate_document_filter:
        candidate_bound = f"""
          AND document_id IN (
              SELECT DISTINCT document_id
              FROM document_embeddings
              WHERE model_name = {{model_name}}
                AND product = 'signals'
                AND document_type = 'signal'
                AND {candidate_document_filter}
          )"""

    return f"""
        SELECT
            {selected_columns_sql}
        FROM document_embeddings
        WHERE model_name = {{model_name}}
          AND product = 'signals'
          AND document_type = 'signal'{candidate_bound}
        GROUP BY document_id
    """


# Backwards-compatible aliases for callers that import the shared query constants directly.
_DEDUPED_SIGNALS_SUBQUERY = _deduped_signals_subquery()


def _signals_for_report_query(*, include_deleted: bool = False, limit: int | None = None) -> str:
    """Build a HogQL query that fetches signal rows for a single report.

    Args:
        include_deleted: When True the ``NOT deleted`` filter is omitted.
            Used by soft-delete which intentionally re-processes already-deleted rows.
        limit: Optional row cap appended as a LIMIT clause.
    """
    deleted_filter = "" if include_deleted else "\n          AND NOT JSONExtractBool(metadata, 'deleted')"
    limit_clause = "" if limit is None else f"\n        LIMIT {limit}"

    return f"""
        SELECT
            document_id,
            content,
            metadata,
            timestamp
        FROM ({_deduped_signals_subquery(candidate_document_filter="JSONExtractString(metadata, 'report_id') = {report_id}")})
        WHERE JSONExtractString(metadata, 'report_id') = {{report_id}}{deleted_filter}
        ORDER BY timestamp ASC{limit_clause}
    """


def _report_placeholders(report_id: str) -> dict:
    return {
        "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
        "report_id": ast.Constant(value=report_id),
    }


def _parse_signal_row(row: tuple) -> SignalData:
    """Turn a (document_id, content, metadata_str, timestamp) row into a SignalData."""
    document_id, content, metadata_str, timestamp_raw = row
    timestamp_raw = _ensure_tz_aware(timestamp_raw)
    # Purposefully throw here if we fail - we rely on metadata being correct, and it's not llm generated, so
    # no defensive parsing, we want to fail loudly.
    metadata = json.loads(metadata_str)
    return SignalData(
        signal_id=document_id,
        content=content,
        source_product=metadata.get("source_product", ""),
        source_type=metadata.get("source_type", ""),
        source_id=metadata.get("source_id", ""),
        weight=metadata.get("weight", 0.0),
        timestamp=timestamp_raw,
        extra=metadata.get("extra", {}),
        remediation=metadata.get("remediation"),
    )


# ---------------------------------------------------------------------------
# soft_delete_report_signals — synchronous, called from reingestion activity
# ---------------------------------------------------------------------------


def soft_delete_report_signals(report_id: str, team_id: int, team: Team) -> None:
    """
    Soft-delete all ClickHouse signals for a report by re-emitting them with metadata.deleted=True.

    Preserves the original timestamp so each row lands in the same ReplacingMergeTree partition
    and replaces the original. Intentionally fetches ALL signals (including already-deleted ones)
    so no signals are missed on repeated calls.
    """
    result = execute_hogql_query(
        query_type="SignalsSoftDeleteForReport",
        query=_signals_for_report_query(include_deleted=True, limit=5000),
        team=team,
        placeholders=_report_placeholders(report_id),
    )

    for row in result.results or []:
        document_id, content, metadata_str, timestamp_raw = row
        metadata = json.loads(metadata_str)
        metadata["deleted"] = True

        emit_embedding_request(
            content=content,
            team_id=team_id,
            product=SIGNAL_DOCUMENT_PRODUCT,
            document_type=SIGNAL_DOCUMENT_TYPE,
            rendering=SIGNAL_DOCUMENT_RENDERING,
            document_id=document_id,
            models=[m.value for m in EmbeddingModelName],
            timestamp=_ensure_tz_aware(timestamp_raw),
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# fetch_signal_type_examples_activity
# ---------------------------------------------------------------------------


@dataclass
class FetchSignalTypeExamplesInput:
    team_id: int


@dataclass
class FetchSignalTypeExamplesOutput:
    examples: list[SignalTypeExample]


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def fetch_signal_type_examples_activity(input: FetchSignalTypeExamplesInput) -> FetchSignalTypeExamplesOutput:
    """Fetch one example signal per unique (source_product, source_type) pair from ClickHouse."""
    try:
        team = await Team.objects.aget(pk=input.team_id)

        query = f"""
            SELECT -- Grab the latest unique example of each signal type
                source_product,
                source_type,
                argMax(content, timestamp) as example_content,
                argMax(metadata, timestamp) as example_metadata,
                toString(max(timestamp)) as latest_timestamp
            FROM ( -- From the set of most recent versions where the signal appeared at most a month ago
                SELECT
                    JSONExtractString(metadata, 'source_product') as source_product,
                    JSONExtractString(metadata, 'source_type') as source_type,
                    content,
                    metadata,
                    timestamp
                FROM ({_deduped_signals_subquery()})
                WHERE content != ''
                  AND timestamp >= now() - INTERVAL 1 MONTH
                  AND NOT JSONExtractBool(metadata, 'deleted')
            )
            GROUP BY source_product, source_type
        """

        result = await execute_hogql_query_with_retry(
            query_type="SignalsFetchTypeExamples",
            query=query,
            team=team,
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            },
        )

        examples = []
        for row in result.results or []:
            source_product, source_type, content, metadata_str, timestamp = row
            metadata = json.loads(metadata_str)
            examples.append(
                SignalTypeExample(
                    source_product=source_product,
                    source_type=source_type,
                    content=content,
                    timestamp=timestamp,
                    extra=metadata.get("extra", {}),
                )
            )

        logger.debug(
            f"Fetched {len(examples)} signal type examples for team {input.team_id}",
            team_id=input.team_id,
            example_count=len(examples),
        )
        return FetchSignalTypeExamplesOutput(examples=examples)
    except Exception as e:
        logger.exception(
            f"Failed to fetch signal type examples for team {input.team_id}: {e}",
            team_id=input.team_id,
        )
        raise


# ---------------------------------------------------------------------------
# run_signal_semantic_search_activity
# ---------------------------------------------------------------------------


@dataclass
class RunSignalSemanticSearchInput:
    team_id: int
    embedding: list[float]
    limit: int = 10


@dataclass
class RunSignalSemanticSearchOutput:
    candidates: list[SignalCandidate]


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def run_signal_semantic_search_activity(input: RunSignalSemanticSearchInput) -> RunSignalSemanticSearchOutput:
    """Run a nearest neighbor query against the signal embeddings in ClickHouse."""
    try:
        team = await Team.objects.aget(pk=input.team_id)

        query = f"""
            SELECT
                document_id,
                content,
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractString(metadata, 'source_product') as source_product,
                JSONExtractString(metadata, 'source_type') as source_type,
                cosineDistance(embedding, {{embedding}}) as distance
            FROM ({_deduped_signals_subquery(include_embedding=True)})
            WHERE JSONExtractString(metadata, 'report_id') != ''
              AND timestamp >= now() - INTERVAL 1 MONTH
              AND NOT JSONExtractBool(metadata, 'deleted')
            ORDER BY distance ASC
            LIMIT {{limit}}
        """

        result = await execute_hogql_query_with_retry(
            query_type="SignalsRunEmbeddingQuery",
            query=query,
            team=team,
            placeholders={
                "embedding": ast.Constant(value=input.embedding),
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "limit": ast.Constant(value=input.limit),
            },
        )

        candidates = []
        for row in result.results or []:
            document_id, content, report_id, source_product, source_type, distance = row
            candidates.append(
                SignalCandidate(
                    signal_id=document_id,
                    report_id=report_id,
                    content=content,
                    source_product=source_product,
                    source_type=source_type,
                    distance=distance,
                )
            )

        logger.debug(
            f"Found {len(candidates)} candidate signals for team {input.team_id}",
            team_id=input.team_id,
            candidate_count=len(candidates),
        )
        return RunSignalSemanticSearchOutput(candidates=candidates)
    except Exception as e:
        logger.exception(
            f"Failed to run embedding query for team {input.team_id}: {e}",
            team_id=input.team_id,
        )
        raise


# ---------------------------------------------------------------------------
# wait_for_signal_in_clickhouse_activity
# ---------------------------------------------------------------------------


@dataclass
class WaitForClickHouseSignal:
    signal_id: str
    timestamp: datetime


@dataclass
class WaitForClickHouseInput:
    team_id: int
    signals: list[WaitForClickHouseSignal]
    max_wait_time_seconds: int = 3600


async def _all_signals_recently_seen(team_id: int, signals: list[WaitForClickHouseSignal]) -> bool:
    """Check the embedding worker's recently-seen store for every signal's emission.

    True only when each signal's document reports an emit timestamp at or after the
    signal's own timestamp (minus a small precision tolerance) — the store records the
    request's timestamp field verbatim, so a fresh emission is confirmed the moment the
    worker commits it, while a record left over from an older emission of the same
    document_id fails the comparison. False on any miss, stale record, or store error.

    A True result is a hint, not proof of ClickHouse visibility: "seen" means committed
    to the output Kafka topic, and a soft-delete re-emission reuses the original
    timestamp so it is indistinguishable from the original emission here. Callers must
    still confirm against ClickHouse.
    """
    documents = [
        DocumentKey(
            product=SIGNAL_DOCUMENT_PRODUCT,
            document_type=SIGNAL_DOCUMENT_TYPE,
            rendering=SIGNAL_DOCUMENT_RENDERING,
            document_id=s.signal_id,
        )
        for s in signals
    ]
    try:
        seen = await async_get_recently_seen_documents(documents, team_id=team_id)
    except Exception:
        logger.warning(
            "Recently-seen lookup failed, falling back to ClickHouse polling",
            team_id=team_id,
            exc_info=True,
        )
        return False

    for document, signal in zip(documents, signals):
        emitted_at = seen.get(document)
        if emitted_at is None or emitted_at < _ensure_tz_aware(signal.timestamp) - RECENTLY_SEEN_TIMESTAMP_TOLERANCE:
            return False
    return True


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def wait_for_signal_in_clickhouse_activity(input: WaitForClickHouseInput) -> None:
    """Wait until all emitted signals land in ClickHouse, or give up after max_wait_time_seconds.

    Two-tier poll. Every attempt checks the embedding worker's recently-seen store (a
    cheap key-value lookup); the ClickHouse confirmation query runs only once the store
    confirms the emission, or on every CH_CONFIRM_EVERY_N_ATTEMPTS-th attempt as a
    fallback for when the store is lossy. ClickHouse stays authoritative — the store
    only tracks the worker's Kafka commit, which precedes the ClickHouse insert.

    The ClickHouse query filters on inserted_at >= (now - 30 minutes) to avoid matching
    stale rows from a previous emission of the same document_id (e.g. deleted then
    reingested). The window is generous because signals are emitted during the
    sequential phase before this activity starts, so early signals may already be
    minutes old.
    """
    if not input.signals:
        return

    from django.utils import timezone

    team = await Team.objects.aget(pk=input.team_id)
    inserted_at_threshold = timezone.now() - timedelta(minutes=30)
    max_attempts = max(1, input.max_wait_time_seconds // WAIT_POLL_INTERVAL_SECONDS)

    signal_ids = [s.signal_id for s in input.signals]
    timestamps = [s.timestamp for s in input.signals]
    # Widen the timestamp range to account for precision loss (Python microseconds vs ClickHouse DateTime64(3) milliseconds)
    min_timestamp = min(timestamps) - timedelta(minutes=2)
    max_timestamp = max(timestamps) + timedelta(minutes=2)

    query = """
        SELECT count(DISTINCT document_id)
        FROM document_embeddings
        WHERE timestamp >= {min_timestamp}
          AND timestamp <= {max_timestamp}
          AND product = 'signals'
          AND document_type = 'signal'
          AND model_name = {model_name}
          AND rendering = 'plain'
          AND document_id IN {signal_ids}
          AND inserted_at >= {inserted_at_threshold}
    """

    placeholders = {
        "min_timestamp": ast.Constant(value=min_timestamp),
        "max_timestamp": ast.Constant(value=max_timestamp),
        "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
        "signal_ids": ast.Constant(value=signal_ids),
        "inserted_at_threshold": ast.Constant(value=inserted_at_threshold),
    }

    expected_count = len(signal_ids)

    store_confirmed = False
    for attempt in range(max_attempts):
        temporalio.activity.heartbeat(attempt)

        if not store_confirmed:
            store_confirmed = await _all_signals_recently_seen(input.team_id, input.signals)
            if store_confirmed:
                logger.debug(
                    f"Recently-seen store confirmed all {expected_count} signal(s) after {attempt + 1} attempt(s)",
                    signal_ids=signal_ids,
                    team_id=input.team_id,
                )

        ch_confirm_due = (
            store_confirmed
            or attempt % CH_CONFIRM_EVERY_N_ATTEMPTS == CH_CONFIRM_EVERY_N_ATTEMPTS - 1
            or attempt == max_attempts - 1
        )
        if ch_confirm_due:
            result = await execute_hogql_query_with_retry(
                query_type="SignalsWaitForClickHouse",
                query=query,
                team=team,
                placeholders=placeholders,
                heartbeat_fn=temporalio.activity.heartbeat,
            )

            # Heartbeat immediately after the query completes — the query itself runs in
            # sync_to_async and can't heartbeat during execution, so this ensures we don't
            # hit the heartbeat timeout when queries are slow.
            temporalio.activity.heartbeat(attempt)

            if result.results and result.results[0][0] >= expected_count:
                logger.debug(
                    f"All {expected_count} signal(s) found in ClickHouse after {attempt + 1} attempt(s)",
                    signal_ids=signal_ids,
                    team_id=input.team_id,
                )
                return

        # Sleep in chunks so we keep heartbeating during the poll interval
        remaining = WAIT_POLL_INTERVAL_SECONDS
        while remaining > 0:
            chunk = min(remaining, 5)
            await asyncio.sleep(chunk)
            remaining -= chunk
            temporalio.activity.heartbeat(attempt)

    metrics.increment_ch_wait_timeout()
    logger.warning(
        f"Not all signals found in ClickHouse after {input.max_wait_time_seconds}s, proceeding anyway",
        signal_ids=signal_ids,
        team_id=input.team_id,
    )


# ---------------------------------------------------------------------------
# fetch_signals_for_report — async activity + sync helper for views
# ---------------------------------------------------------------------------


@dataclass
class FetchSignalsForReportInput:
    team_id: int
    report_id: str


@dataclass
class FetchSignalsForReportOutput:
    signals: list[SignalData]


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def fetch_signals_for_report_activity(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
    try:
        team = await Team.objects.aget(pk=input.team_id)

        result = await execute_hogql_query_with_retry(
            query_type="SignalsFetchForReport",
            query=_signals_for_report_query(),
            team=team,
            placeholders=_report_placeholders(input.report_id),
        )

        signals = [_parse_signal_row(row) for row in (result.results or [])]

        logger.debug(
            f"Fetched {len(signals)} signals for report {input.report_id}",
            team_id=input.team_id,
            report_id=input.report_id,
            signal_count=len(signals),
        )
        return FetchSignalsForReportOutput(signals=signals)
    except Exception as e:
        logger.exception(
            f"Failed to fetch signals for report {input.report_id}: {e}",
            team_id=input.team_id,
            report_id=input.report_id,
        )
        raise


def fetch_signals_for_report_sync(team: Team, report_id: str) -> list[dict]:
    """Fetch all signals for a report from ClickHouse, including full metadata. Synchronous."""
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsDebugFetchForReport",
        query=_signals_for_report_query(),
        team=team,
        placeholders=_report_placeholders(report_id),
    )

    signals_list = []
    for row in result.results or []:
        document_id, content, metadata_str, timestamp = row
        metadata = json.loads(metadata_str)
        signals_list.append(
            {
                "signal_id": document_id,
                "content": content,
                "source_product": metadata.get("source_product", ""),
                "source_type": metadata.get("source_type", ""),
                "source_id": metadata.get("source_id", ""),
                "weight": metadata.get("weight", 0.0),
                "timestamp": timestamp,
                "extra": metadata.get("extra", {}),
                "match_metadata": metadata.get("match_metadata"),
            }
        )

    return signals_list


# ---------------------------------------------------------------------------
# fetch_report_ids_for_source_products — synchronous, for the viewset list filter
# ---------------------------------------------------------------------------


def fetch_report_ids_for_source_products(team: Team, source_products: list[str]) -> set[str]:
    """Return the set of report IDs that have at least one non-deleted signal from the given source products.

    Uses argMax deduplication to give stable results regardless of ReplacingMergeTree merge state.
    """
    ch_query = f"""
        SELECT DISTINCT report_id
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'source_product') as source_product,
                timestamp
            FROM ({_deduped_signals_subquery()})
            ORDER BY timestamp DESC
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND source_product IN ({{source_products}})
        LIMIT 300
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFilterBySourceProduct",
        query=ch_query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "source_products": ast.Tuple(exprs=[ast.Constant(value=sp) for sp in source_products]),
        },
    )

    return {row[0] for row in (result.results or []) if row[0]}


# ---------------------------------------------------------------------------
# fetch_report_ids_for_source_ids — synchronous, for the scout reverse lookup
# ---------------------------------------------------------------------------


def fetch_report_ids_for_source_ids(team: Team, source_ids: list[str]) -> dict[str, str]:
    """Map each scout `source_id` to the report its emitted signal grouped into.

    Best-effort reverse of the report -> signals link. A scout finding is emitted as a
    signal whose ClickHouse metadata carries both its deterministic `source_id`
    (`run:<run_id>:finding:<finding_id>`) and, once grouping matches it, the `report_id`
    of the report it landed in. This walks that link backwards so the scout UI can show
    which inbox report (if any) a finding contributed to.

    Only `signals_scout` signals that resolved to a non-empty, non-deleted `report_id`
    are returned. A non-idempotent re-emit can produce several signals for one
    `source_id`; the most recent (by signal timestamp) wins. Uses argMax dedup so the
    result is stable regardless of ReplacingMergeTree merge state.
    """
    if not source_ids:
        return {}

    # Push the source_id filter into the document_embeddings scan so we only dedup the
    # handful of signals for these findings, not the team's entire signal history.
    # Resolve the newest signal per source_id FIRST (carrying its deleted/report state),
    # then decide whether to return a link. Filtering deleted/empty rows before the argMax
    # would let an older non-deleted report win when the latest signal was deleted or
    # report-less, surfacing a stale link instead of the documented "most recent wins" null.
    source_id_scan_filter = "JSONExtractString(metadata, 'source_id') IN ({source_ids})"
    ch_query = f"""
        SELECT source_id, report_id
        FROM (
            SELECT
                source_id,
                argMax(report_id, timestamp) as report_id,
                argMax(is_deleted, timestamp) as is_deleted
            FROM (
                SELECT
                    JSONExtractString(metadata, 'source_id') as source_id,
                    JSONExtractString(metadata, 'report_id') as report_id,
                    JSONExtractBool(metadata, 'deleted') as is_deleted,
                    JSONExtractString(metadata, 'source_product') as source_product,
                    timestamp
                FROM ({_deduped_signals_subquery(extra_where=source_id_scan_filter)})
            )
            WHERE source_product = 'signals_scout'
              AND source_id != ''
            GROUP BY source_id
        )
        WHERE NOT is_deleted
          AND report_id != ''
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFetchReportIdsForSourceIds",
        query=ch_query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "source_ids": ast.Tuple(exprs=[ast.Constant(value=sid) for sid in source_ids]),
        },
    )

    return {row[0]: row[1] for row in (result.results or []) if row[0] and row[1]}
