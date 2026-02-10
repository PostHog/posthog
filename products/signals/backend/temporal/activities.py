import os
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
from products.signals.backend.temporal.llm import match_signal_with_llm
from products.signals.backend.temporal.types import ExistingReportMatch, MatchResult, NewReportMatch, SignalCandidate

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
class GetNearestSignalsInput:
    team_id: int
    embedding: list[float]
    limit: int = 10


@dataclass
class GetNearestSignalsOutput:
    candidates: list[SignalCandidate]


@temporalio.activity.defn
async def get_nearest_assigned_signals_activity(input: GetNearestSignalsInput) -> GetNearestSignalsOutput:
    """Find nearest signals that are already assigned to a report via ClickHouse vector search."""
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
            FROM document_embeddings
            WHERE model_name = {model_name}
              AND product = 'signals'
              AND document_type = 'signal'
              AND JSONExtractString(metadata, 'report_id') != ''
              AND timestamp >= now() - INTERVAL 1 MONTH
            ORDER BY distance ASC
            LIMIT {limit}
        """

        result = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
            query_type="SignalsGetNearestAssigned",
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
        return GetNearestSignalsOutput(candidates=candidates)
    except Exception as e:
        logger.exception(
            f"Failed to get nearest signals for team {input.team_id}: {e}",
            team_id=input.team_id,
        )
        raise


@dataclass
class LLMMatchSignalInput:
    description: str
    source_product: str
    source_type: str
    candidates: list[SignalCandidate]


@temporalio.activity.defn
async def llm_match_signal_activity(input: LLMMatchSignalInput) -> MatchResult:
    """Use LLM to determine if new signal matches an existing report or needs a new one."""
    try:
        result = await match_signal_with_llm(
            description=input.description,
            source_product=input.source_product,
            source_type=input.source_type,
            candidates=input.candidates,
        )
        logger.debug(
            f"LLM match result: matched={isinstance(result, ExistingReportMatch)}",
            candidate_count=len(input.candidates),
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
