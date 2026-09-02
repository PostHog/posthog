import json
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
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

from products.signals.backend.signal_metadata import (
    EMBEDDING_MODEL,
    SIGNAL_DOCUMENT_PRODUCT,
    SIGNAL_DOCUMENT_RENDERING,
    SIGNAL_DOCUMENT_TYPE,
    _deduped_signals_subquery,
)
from products.signals.backend.temporal import metrics
from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry
from products.signals.backend.temporal.types import SignalCandidate, SignalData, SignalTypeExample

logger = structlog.get_logger(__name__)


WAIT_POLL_INTERVAL_SECONDS = 10

# For this long, ClickHouse is polled only when the recently-seen store confirms the
# emission (or on the final attempt) — the wait is store-exclusive to keep ClickHouse
# load off the polling path. After it, ClickHouse also polls on the fallback cadence
# below, because the store is best-effort (writes never block ingestion, and the
# in-memory backend is per-pod), so a negative answer can't gate ClickHouse forever.
CH_CONFIRM_GRACE_PERIOD_SECONDS = 300

# Fallback cadence once the grace period has elapsed without store confirmation: the
# store keeps polling every attempt, ClickHouse only every Nth — 3x fewer CH queries.
CH_CONFIRM_EVERY_N_ATTEMPTS = 3


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
            timestamp,
            latest_inserted_at
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
    """Turn a ClickHouse document embedding row into a SignalData."""
    document_id, content, metadata_str, timestamp_raw, inserted_at_raw = row
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
        inserted_at=_ensure_tz_aware(inserted_at_raw),
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
        document_id, content, metadata_str, timestamp_raw, _inserted_at_raw = row
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
    inserted_at: datetime | None = None


class WaitForClickHouseMode(StrEnum):
    """How much the wait trusts the recently-seen store vs ClickHouse.

    OPTIMISTIC: return as soon as the store confirms the emission, without querying
    ClickHouse at all — cheapest and fastest, but blind to the Kafka-to-ClickHouse
    insert gap. ClickHouse still polls on the post-grace fallback cadence when the
    store never confirms.

    CH_CONFIRMED: a store confirmation triggers an immediate ClickHouse confirm, and
    ClickHouse stays authoritative — the store only decides when to start querying.

    """

    OPTIMISTIC = "optimistic"
    CH_CONFIRMED = "ch_confirmed"


@dataclass
class WaitForClickHouseInput:
    team_id: int
    signals: list[WaitForClickHouseSignal]
    max_wait_time_seconds: int = 3600
    mode: WaitForClickHouseMode = WaitForClickHouseMode.CH_CONFIRMED


async def _all_signals_recently_seen(team_id: int, signals: list[WaitForClickHouseSignal]) -> bool:
    """Check the embedding worker's recently-seen store for every signal's emission.

    True only when each document is present and, when its current ClickHouse inserted_at
    is known, the worker emitted it after that version. False on any miss, stale record,
    or store error.

    A True result is not proof of ClickHouse visibility: "seen" means committed to the
    output Kafka topic. WaitForClickHouseMode decides how much the caller trusts it.
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
        metrics.increment_recently_seen_lookup("error")
        logger.warning(
            "Recently-seen lookup failed; scheduled ClickHouse fallback remains active",
            team_id=team_id,
            exc_info=True,
        )
        return False

    for document, signal in zip(documents, signals):
        emitted_at = seen.get(document)
        if emitted_at is None:
            metrics.increment_recently_seen_lookup("pending")
            return False
        if signal.inserted_at is not None and emitted_at <= _ensure_tz_aware(signal.inserted_at):
            metrics.increment_recently_seen_lookup("pending")
            return False
    metrics.increment_recently_seen_lookup("confirmed")
    return True


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def wait_for_signal_in_clickhouse_activity(input: WaitForClickHouseInput) -> None:
    """Wait until all emitted signals are processed, or give up after max_wait_time_seconds.

    Two-tier poll, tuned by input.mode (see WaitForClickHouseMode). Every attempt checks
    the embedding worker's recently-seen store (a cheap key-value lookup): a store
    confirmation ends the wait outright in OPTIMISTIC mode, or triggers the ClickHouse
    confirmation query in CH_CONFIRMED mode. For the first
    CH_CONFIRM_GRACE_PERIOD_SECONDS the wait is otherwise store-exclusive; after that,
    ClickHouse also polls on every CH_CONFIRM_EVERY_N_ATTEMPTS-th attempt (a third of
    the store's rate) as a fallback for when the store is lossy, plus once on the
    final attempt before giving up. The store only tracks the worker's Kafka commit,
    which precedes the ClickHouse insert — modes trade that gap against ClickHouse
    load.

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
                if input.mode == WaitForClickHouseMode.OPTIMISTIC:
                    metrics.increment_ch_wait_completion(input.mode.value, "recently_seen")
                    return

        past_grace_period = attempt * WAIT_POLL_INTERVAL_SECONDS >= CH_CONFIRM_GRACE_PERIOD_SECONDS
        ch_confirm_due = (
            store_confirmed
            or (past_grace_period and attempt % CH_CONFIRM_EVERY_N_ATTEMPTS == CH_CONFIRM_EVERY_N_ATTEMPTS - 1)
            or attempt == max_attempts - 1
        )
        if ch_confirm_due:
            if store_confirmed:
                query_reason = "store_confirmed"
            elif attempt == max_attempts - 1:
                query_reason = "final"
            else:
                query_reason = "fallback"
            metrics.increment_ch_wait_query(input.mode.value, query_reason)
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
                metrics.increment_ch_wait_completion(input.mode.value, "clickhouse")
                return

        # Sleep in chunks so we keep heartbeating during the poll interval
        remaining = WAIT_POLL_INTERVAL_SECONDS
        while remaining > 0:
            chunk = min(remaining, 5)
            await asyncio.sleep(chunk)
            remaining -= chunk
            temporalio.activity.heartbeat(attempt)

    metrics.increment_ch_wait_timeout()
    metrics.increment_ch_wait_completion(input.mode.value, "timeout")
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
        document_id, content, metadata_str, timestamp, _inserted_at = row
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

# Bounds the report-id set handed to the Django `id__in` inbox filters (source/scout). The cap is
# applied after a deterministic `ORDER BY max(timestamp) DESC`, so it keeps the most-recently-active
# matching reports and the same set across list/count calls.
_REPORT_ID_FILTER_CAP = 300


def fetch_report_ids_for_source_products(team: Team, source_products: list[str]) -> set[str]:
    """Return the set of report IDs that have at least one non-deleted signal from the given source products.

    Uses argMax deduplication to give stable results regardless of ReplacingMergeTree merge state.
    Capped at `_REPORT_ID_FILTER_CAP` most-recently-active matching reports after a deterministic
    `ORDER BY` so the list and count requests that both call this see the identical truncated set.
    """
    ch_query = f"""
        SELECT report_id
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'source_product') as source_product,
                timestamp
            FROM ({_deduped_signals_subquery()})
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND source_product IN ({{source_products}})
        GROUP BY report_id
        ORDER BY max(timestamp) DESC
        LIMIT {_REPORT_ID_FILTER_CAP}
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
# fetch_report_ids_for_scout_names — synchronous, for the viewset list filter
# ---------------------------------------------------------------------------


def fetch_report_ids_for_scout_names(team: Team, scout_names: list[str]) -> set[str]:
    """Return the set of report IDs that have at least one non-deleted signal authored by the given scouts.

    Scout-emitted signals carry the authoring scout's raw skill_name slug (e.g.
    "signals-scout-error-tracking") in `extra.skill_name`; other sources leave it empty, so
    matching on it alone is already scoped to scout signals. Uses argMax deduplication to give
    stable results regardless of ReplacingMergeTree merge state.

    Capped at `_REPORT_ID_FILTER_CAP` most-recently-active matching reports (by newest signal
    timestamp). The cap is applied after a deterministic `ORDER BY` so the list and count requests
    that both call this see the identical set — without the ordering the truncated set could differ
    between calls, flickering reports in and out across refreshes.
    """
    ch_query = f"""
        SELECT report_id
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'extra', 'skill_name') as skill_name,
                timestamp
            FROM ({_deduped_signals_subquery()})
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND skill_name IN ({{scout_names}})
        GROUP BY report_id
        ORDER BY max(timestamp) DESC
        LIMIT {_REPORT_ID_FILTER_CAP}
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFilterByScoutName",
        query=ch_query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "scout_names": ast.Tuple(exprs=[ast.Constant(value=name) for name in scout_names]),
        },
    )

    return {row[0] for row in (result.results or []) if row[0]}


def fetch_report_ids_for_scout_prefix(team: Team, scout_prefix: str) -> set[str]:
    """Return the set of report IDs that have at least one non-deleted signal authored by a scout
    whose skill_name starts with `scout_prefix`.

    Prefix matching lets a scout family (e.g. every customer-analytics scout named
    `signals-scout-customer-analytics*`) surface new members without callers updating a name list.
    Same dedup, ordering, and cap semantics as `fetch_report_ids_for_scout_names`.
    """
    ch_query = f"""
        SELECT report_id
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'extra', 'skill_name') as skill_name,
                timestamp
            FROM ({_deduped_signals_subquery()})
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND skill_name != ''
          AND startsWith(skill_name, {{scout_prefix}})
        GROUP BY report_id
        ORDER BY max(timestamp) DESC
        LIMIT {_REPORT_ID_FILTER_CAP}
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFilterByScoutPrefix",
        query=ch_query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "scout_prefix": ast.Constant(value=scout_prefix),
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


def fetch_live_report_ids_for_source_ids(
    team: Team, source_ids: list[str], source_product: str | None = None
) -> dict[str, list[str]]:
    """Map each `source_id` to every live report its signals grouped into, newest report first.

    Sibling of `fetch_report_ids_for_source_ids`, which answers a different question: that one
    collapses to the single latest report because a scout finding's re-emit is non-idempotent and
    the older link is stale. A source record can legitimately produce several distinct signals over
    time (a support ticket is re-snapshotted as its thread grows), and those can land in different
    reports, so here every live link is a real answer rather than a stale one.

    Dedup runs per `document_id` first, so each signal contributes its current report and deleted
    state; only then are deleted and report-less signals dropped. Doing it in that order is what
    keeps a superseded version of a signal from resurrecting an old link.
    """
    if not source_ids:
        return {}

    source_id_scan_filter = "JSONExtractString(metadata, 'source_id') IN ({source_ids})"
    product_filter = "AND source_product = {source_product}" if source_product is not None else ""
    ch_query = f"""
        SELECT source_id, groupArray(report_id) as report_ids
        FROM (
            SELECT
                JSONExtractString(metadata, 'source_id') as source_id,
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'source_product') as source_product,
                max(timestamp) as latest_timestamp
            FROM ({_deduped_signals_subquery(extra_where=source_id_scan_filter)})
            GROUP BY source_id, report_id, is_deleted, source_product
            ORDER BY latest_timestamp DESC
        )
        WHERE NOT is_deleted
          AND source_id != ''
          AND report_id != ''
          {product_filter}
        GROUP BY source_id
    """

    placeholders: dict[str, ast.Expr] = {
        "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
        "source_ids": ast.Tuple(exprs=[ast.Constant(value=sid) for sid in source_ids]),
    }
    if source_product is not None:
        placeholders["source_product"] = ast.Constant(value=source_product)

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFetchLiveReportIdsForSourceIds",
        query=ch_query,
        team=team,
        placeholders=placeholders,
    )

    return {row[0]: list(row[1]) for row in (result.results or []) if row[0] and row[1]}
