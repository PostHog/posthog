import os
import json
import uuid
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

import structlog
import temporalio
from asgiref.sync import sync_to_async
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import emit_embedding_request, generate_embedding
from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.llm import generate_search_queries, match_signal_with_llm
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    SignalCandidate,
    SignalTypeExample,
)

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536
WEIGHT_THRESHOLD = float(os.getenv("SIGNAL_WEIGHT_THRESHOLD", "1.0"))


# ============================================================================
# Activities
# ============================================================================


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
class FetchSignalTypeExamplesInput:
    team_id: int


@dataclass
class FetchSignalTypeExamplesOutput:
    examples: list[SignalTypeExample]


@temporalio.activity.defn
async def fetch_signal_type_examples_activity(input: FetchSignalTypeExamplesInput) -> FetchSignalTypeExamplesOutput:
    """Fetch one example signal per unique (source_product, source_type) pair from ClickHouse."""
    try:
        team = await Team.objects.aget(pk=input.team_id)

        query = """
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
                FROM ( -- From the most recent versions of all signals
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
                WHERE content != ''
                  AND timestamp >= now() - INTERVAL 1 MONTH
            )
            GROUP BY source_product, source_type
        """

        result = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
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
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str or {}
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


@dataclass
class GenerateSearchQueriesInput:
    description: str
    source_product: str
    source_type: str
    signal_type_examples: list[SignalTypeExample]


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
            signal_type_examples=input.signal_type_examples,
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
# Workflow
# ============================================================================


# TODO: Not idempotent on source_id - re-running with the same source_id will create duplicate signals.
# Need to check ClickHouse for existing signal before processing.
@temporalio.workflow.defn(name="emit-signal")
class EmitSignalWorkflow:
    """
    Workflow for processing a new signal.

    Flow:
    1. Generate embedding for signal content
    2. Find nearest signals already assigned to reports
    3. LLM determines if new signal matches an existing report
    4. Create or update report, check for promotion
    5. Emit signal to ClickHouse with correct report_id
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitSignalInputs:
        loaded = json.loads(inputs[0])
        return EmitSignalInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, source_product: str, source_type: str, source_id: str) -> str:
        # Prevents the same signal from being processed simultaneously, but does NOT
        # prevent re-running the workflow for the same source_id (see TODO above).
        return f"{team_id}:{source_product}:{source_type}:{source_id}"

    @temporalio.workflow.run
    async def run(self, inputs: EmitSignalInputs) -> str:
        # Import here to avoid circular imports (summary imports are only needed for child workflow spawn)
        from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow

        with workflow.unsafe.imports_passed_through():
            from django.conf import settings

        signal_id = str(uuid.uuid4())

        # Fetch signal type examples and embedding in parallel (examples needed for query generation)
        embedding_result, type_examples_result = await asyncio.gather(
            workflow.execute_activity(
                get_embedding_activity,
                GenerateEmbeddingInput(team_id=inputs.team_id, content=inputs.description),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
            workflow.execute_activity(
                fetch_signal_type_examples_activity,
                FetchSignalTypeExamplesInput(team_id=inputs.team_id),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )

        search_queries_result = await workflow.execute_activity(
            generate_search_queries_activity,
            GenerateSearchQueriesInput(
                description=inputs.description,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                signal_type_examples=type_examples_result.examples,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        queries = search_queries_result.queries

        query_embedding_results: list[GenerateEmbeddingOutput] = await asyncio.gather(
            *[
                workflow.execute_activity(
                    get_embedding_activity,
                    GenerateEmbeddingInput(team_id=inputs.team_id, content=query),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for query in queries
            ]
        )

        query_results: list[RunSignalSemanticSearchOutput] = await asyncio.gather(
            *[
                workflow.execute_activity(
                    run_signal_semantic_search_activity,
                    RunSignalSemanticSearchInput(
                        team_id=inputs.team_id,
                        embedding=emb_result.embedding,
                        limit=10,
                    ),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for emb_result in query_embedding_results
            ]
        )

        match_result = await workflow.execute_activity(
            llm_match_signal_activity,
            LLMMatchSignalInput(
                description=inputs.description,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                queries=queries,
                query_results=[r.candidates for r in query_results],
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        assign_result: AssignSignalOutput = await workflow.execute_activity(
            assign_signal_to_report_activity,
            AssignSignalInput(
                team_id=inputs.team_id,
                signal_id=signal_id,
                description=inputs.description,
                weight=inputs.weight,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                source_id=inputs.source_id,
                extra=inputs.extra,
                embedding=embedding_result.embedding,
                match_result=match_result,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        await workflow.execute_activity(
            emit_to_clickhouse_activity,
            EmitToClickHouseInput(
                team_id=inputs.team_id,
                signal_id=signal_id,
                description=inputs.description,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                source_id=inputs.source_id,
                weight=inputs.weight,
                extra=inputs.extra,
                report_id=assign_result.report_id,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # If the report was just promoted to candidate status, kick off summary
        if assign_result.promoted:
            from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs

            await workflow.start_child_workflow(
                SignalReportSummaryWorkflow.run,
                SignalReportSummaryWorkflowInputs(team_id=inputs.team_id, report_id=assign_result.report_id),
                id=SignalReportSummaryWorkflow.workflow_id_for(inputs.team_id, assign_result.report_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
                execution_timeout=timedelta(minutes=30),
            )

        return signal_id
