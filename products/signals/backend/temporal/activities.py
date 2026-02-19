import os
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

import structlog
import temporalio
from asgiref.sync import sync_to_async

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import emit_embedding_request, generate_embedding
from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.llm import generate_search_queries, match_signal_with_llm, summarize_signals
from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    SignalCandidate,
    SignalData,
)

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536
WEIGHT_THRESHOLD = float(os.getenv("SIGNAL_WEIGHT_THRESHOLD", "1.0"))


@dataclass
class GenerateEmbeddingInput:
    team_id: int
    content: str


@dataclass
class GenerateEmbeddingOutput:
    embedding: list[float]


@temporalio.activity.defn
async def get_embedding_activity(input: GenerateEmbeddingInput) -> GenerateEmbeddingOutput:
    """Generate embedding for signal content using the embedding worker API."""
    try:
        team = await Team.objects.aget(pk=input.team_id)
        response = await sync_to_async(generate_embedding, thread_sensitive=False)(
            team, input.content, model=EMBEDDING_MODEL.value
        )
        logger.debug(
            f"Generated embedding for team {input.team_id}",
            team_id=input.team_id,
            content_length=len(input.content),
        )
        return GenerateEmbeddingOutput(embedding=response.embedding)
    except Exception as e:
        logger.exception(
            f"Failed to generate embedding for team {input.team_id}: {e}",
            team_id=input.team_id,
        )
        raise


@dataclass
class GenerateSearchQueriesInput:
    description: str
    source_product: str
    source_type: str


@dataclass
class GenerateSearchQueriesOutput:
    queries: list[str]


@temporalio.activity.defn
async def generate_search_queries_activity(input: GenerateSearchQueriesInput) -> GenerateSearchQueriesOutput:
    """Use LLM to generate 1-3 search queries for finding related signals."""
    try:
        queries = await generate_search_queries(
            description=input.description,
            source_product=input.source_product,
            source_type=input.source_type,
        )
        logger.debug(
            f"Generated {len(queries)} search queries",
            source_product=input.source_product,
            source_type=input.source_type,
            queries=queries,
        )
        return GenerateSearchQueriesOutput(queries=queries)
    except Exception as e:
        logger.exception(
            f"Failed to generate search queries: {e}",
            source_product=input.source_product,
            source_type=input.source_type,
        )
        raise


@dataclass
class RunSignalSemanticSearchInput:
    team_id: int
    embedding: list[float]
    limit: int = 10


@dataclass
class RunSignalSemanticSearchOutput:
    candidates: list[SignalCandidate]


@temporalio.activity.defn
async def run_signal_semantic_search_activity(input: RunSignalSemanticSearchInput) -> RunSignalSemanticSearchOutput:
    """Run a nearest neighbor query against the signal embeddings in ClickHouse."""
    try:
        team = await Team.objects.aget(pk=input.team_id)

        query = """
            SELECT
                document_id,
                content,
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractString(metadata, 'source_product') as source_product,
                JSONExtractString(metadata, 'source_type') as source_type,
                cosineDistance(embedding, {embedding}) as distance
            FROM (
                SELECT
                    document_id,
                    argMax(content, inserted_at) as content,
                    argMax(metadata, inserted_at) as metadata,
                    argMax(embedding, inserted_at) as embedding,
                    argMax(timestamp, inserted_at) as timestamp
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                GROUP BY document_id
            )
            WHERE JSONExtractString(metadata, 'report_id') != ''
              AND timestamp >= now() - INTERVAL 1 MONTH
            ORDER BY distance ASC
            LIMIT {limit}
        """

        result = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
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


@dataclass
class LLMMatchSignalInput:
    description: str
    source_product: str
    source_type: str
    queries: list[str]
    query_results: list[list[SignalCandidate]]


@temporalio.activity.defn
async def llm_match_signal_activity(input: LLMMatchSignalInput) -> MatchResult:
    """Use LLM to determine if new signal matches an existing report or needs a new one."""
    try:
        result = await match_signal_with_llm(
            description=input.description,
            source_product=input.source_product,
            source_type=input.source_type,
            queries=input.queries,
            query_results=input.query_results,
        )
        total_candidates = sum(len(r) for r in input.query_results)
        logger.debug(
            f"LLM match result: matched={isinstance(result, ExistingReportMatch)}",
            query_count=len(input.queries),
            total_candidates=total_candidates,
        )
        return result
    except Exception as e:
        logger.exception(
            f"Failed to match signal with LLM: {e}",
            source_product=input.source_product,
            source_type=input.source_type,
        )
        raise


@dataclass
class AssignSignalInput:
    team_id: int
    signal_id: str
    description: str
    weight: float
    source_product: str
    source_type: str
    source_id: str
    extra: dict
    embedding: list[float]
    match_result: MatchResult


@dataclass
class AssignSignalOutput:
    report_id: str
    promoted: bool


@temporalio.activity.defn
async def assign_signal_to_report_activity(input: AssignSignalInput) -> AssignSignalOutput:
    """Create or update a SignalReport and check for promotion to candidate status."""

    match_result = input.match_result

    def do_assign() -> tuple[str, bool]:
        with transaction.atomic():
            promoted = False

            if isinstance(match_result, ExistingReportMatch):
                report = SignalReport.objects.select_for_update().get(id=match_result.report_id)
                report.total_weight += input.weight
                report.signal_count += 1
                report.save(update_fields=["total_weight", "signal_count", "updated_at"])
            else:
                report = SignalReport.objects.create(
                    team_id=input.team_id,
                    status=SignalReport.Status.POTENTIAL,
                    total_weight=input.weight,
                    signal_count=1,
                    title=match_result.title,
                    summary=match_result.summary,
                )

            if report.status == SignalReport.Status.POTENTIAL and report.total_weight >= WEIGHT_THRESHOLD:
                report.status = SignalReport.Status.CANDIDATE
                report.promoted_at = timezone.now()
                report.save(update_fields=["status", "promoted_at", "updated_at"])
                promoted = True

            return str(report.id), promoted

    try:
        report_id, promoted = await sync_to_async(do_assign, thread_sensitive=False)()
        logger.debug(
            f"Assigned signal to report {report_id}",
            report_id=report_id,
            team_id=input.team_id,
            promoted=promoted,
            is_new_report=isinstance(match_result, NewReportMatch),
        )
        return AssignSignalOutput(report_id=report_id, promoted=promoted)
    except Exception as e:
        logger.exception(
            f"Failed to assign signal to report: {e}",
            team_id=input.team_id,
            signal_id=input.signal_id,
        )
        raise


@dataclass
class EmitToClickHouseInput:
    team_id: int
    signal_id: str
    description: str
    source_product: str
    source_type: str
    source_id: str
    weight: float
    extra: dict
    report_id: str
    timestamp: Optional[datetime] = None


@temporalio.activity.defn
async def emit_to_clickhouse_activity(input: EmitToClickHouseInput) -> None:
    """Emit signal to Kafka for ClickHouse storage via the embedding worker."""
    try:
        metadata = {
            "source_product": input.source_product,
            "source_type": input.source_type,
            "source_id": input.source_id,
            "weight": input.weight,
            "report_id": input.report_id,
            "extra": input.extra,
        }

        emit_embedding_request(
            content=input.description,
            team_id=input.team_id,
            product="signals",
            document_type="signal",
            rendering="plain",
            document_id=input.signal_id,
            models=[EMBEDDING_MODEL.value],
            timestamp=input.timestamp or timezone.now(),
            metadata=metadata,
        )

        logger.debug(
            f"Emitted signal {input.signal_id} to ClickHouse",
            signal_id=input.signal_id,
            team_id=input.team_id,
            report_id=input.report_id,
        )
    except Exception as e:
        logger.exception(
            f"Failed to emit signal to ClickHouse: {e}",
            signal_id=input.signal_id,
            team_id=input.team_id,
        )
        raise


# ============================================================================
# Research Workflow Activities
# ============================================================================


@dataclass
class FetchSignalsForReportInput:
    team_id: int
    report_id: str


@dataclass
class FetchSignalsForReportOutput:
    signals: list[SignalData]


@temporalio.activity.defn
async def fetch_signals_for_report_activity(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
    """
    Fetch all signals associated with a report from ClickHouse.
    Note: fetches 100 signals at most. This may exceed useful LLM input size - we should consider limiting it in the future.
    """
    try:
        team = await Team.objects.aget(pk=input.team_id)

        query = """
            SELECT
                document_id,
                content,
                metadata,
                toString(timestamp) as timestamp
            FROM (
                SELECT
                    document_id,
                    argMax(content, inserted_at) as content,
                    argMax(metadata, inserted_at) as metadata,
                    argMax(timestamp, inserted_at) as timestamp
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                GROUP BY document_id
            )
            WHERE JSONExtractString(metadata, 'report_id') = {report_id}
            ORDER BY timestamp ASC
        """

        result = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
            query_type="SignalsFetchForReport",
            query=query,
            team=team,
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "report_id": ast.Constant(value=input.report_id),
            },
        )

        signals = []
        for row in result.results or []:
            document_id, content, metadata_str, timestamp = row
            # Purposefully throw here if we fail - we rely on metadata being correct, and it's not llm generated, so
            # no defensive parsing, we want to fail loudly.
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str or {}
            signals.append(
                SignalData(
                    signal_id=document_id,
                    content=content,
                    source_product=metadata.get("source_product", ""),
                    source_type=metadata.get("source_type", ""),
                    source_id=metadata.get("source_id", ""),
                    weight=metadata.get("weight", 0.0),
                    timestamp=timestamp,
                    extra=metadata.get("extra", {}),
                )
            )

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


@dataclass
class MarkReportInProgressInput:
    report_id: str
    signal_count: int


@temporalio.activity.defn
async def mark_report_in_progress_activity(input: MarkReportInProgressInput) -> None:
    """Mark a report as in_progress and record the signal count snapshot."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.IN_PROGRESS
            report.last_run_at = timezone.now()
            report.signals_at_run = input.signal_count
            report.save(update_fields=["status", "last_run_at", "signals_at_run", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as in_progress",
            report_id=input.report_id,
            signal_count=input.signal_count,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as in_progress: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class SummarizeSignalsInput:
    report_id: str
    signals: list[SignalData]


@dataclass
class SummarizeSignalsOutput:
    title: str
    summary: str


@temporalio.activity.defn
async def summarize_signals_activity(input: SummarizeSignalsInput) -> SummarizeSignalsOutput:
    """Summarize signals into a title and summary for the report."""
    try:
        title, summary = await summarize_signals(input.signals)
        logger.debug(
            f"Summarized {len(input.signals)} signals for report {input.report_id}",
            report_id=input.report_id,
            signal_count=len(input.signals),
            title=title,
        )
        return SummarizeSignalsOutput(title=title, summary=summary)
    except Exception as e:
        logger.exception(
            f"Failed to summarize signals for report {input.report_id}: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportReadyInput:
    report_id: str
    title: str
    summary: str


@temporalio.activity.defn
async def mark_report_ready_activity(input: MarkReportReadyInput) -> None:
    """Mark a report as ready after successful summarization."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.READY
            report.title = input.title
            report.summary = input.summary
            report.error = None
            report.save(update_fields=["status", "title", "summary", "error", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as ready",
            report_id=input.report_id,
            title=input.title,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as ready: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportFailedInput:
    report_id: str
    error: str


@temporalio.activity.defn
async def mark_report_failed_activity(input: MarkReportFailedInput) -> None:
    """Mark a report as failed and store the error message."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.FAILED
            report.error = input.error
            report.save(update_fields=["status", "error", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as failed",
            report_id=input.report_id,
            error=input.error,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as failed: {e}",
            report_id=input.report_id,
        )
        raise
