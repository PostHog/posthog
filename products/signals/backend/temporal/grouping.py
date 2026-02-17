import os
import json
import uuid
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
import temporalio
from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.workflow import ParentClosePolicy

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import emit_embedding_request, generate_embedding
from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.llm import MAX_QUERY_TOKENS, call_llm, truncate_query_to_token_limit
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    SignalCandidate,
    SignalTypeExample,
    TeamSignalGroupingInput,
)

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536
WEIGHT_THRESHOLD = float(os.getenv("SIGNAL_WEIGHT_THRESHOLD", "1.0"))
MAX_QUERIES = 3


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
        return f"{team_id}:{source_product}:{source_type}:{source_id}"

    @temporalio.workflow.run
    async def run(self, inputs: EmitSignalInputs) -> str:
        from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow

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

        if assign_result.promoted:
            from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs

            try:
                await workflow.start_child_workflow(
                    SignalReportSummaryWorkflow.run,
                    SignalReportSummaryWorkflowInputs(team_id=inputs.team_id, report_id=assign_result.report_id),
                    id=SignalReportSummaryWorkflow.workflow_id_for(inputs.team_id, assign_result.report_id),
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    execution_timeout=timedelta(minutes=30),
                )
            except temporalio.exceptions.WorkflowAlreadyStartedError:
                pass

        return signal_id


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


class QueryGenerationResponse(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)


QUERY_GENERATION_SYSTEM_PROMPT_TEMPLATE = """You are a signal grouping assistant. Your job is to generate search queries that will help find related signals in an embedding database.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
Related signals may be different types but connected by the same underlying cause, feature, or user journey. Note that "related" does not just mean "semantically similar", but "likely to share a common root cause or impact".

The signal database is heterogeneous — it contains many different signal types. Your queries should search ACROSS these types to find signals that share a common root cause, affected feature, or user journey with the new signal. Do NOT try to generate one query per signal type. Instead, generate queries that would surface related signals regardless of their type.

{examples_section}

Given a new signal, generate 1-3 search queries that would help find related signals. Each query should be a natural language description that captures a different angle of what might be related:

1. The specific feature, page, or component involved
2. The type of user behavior or technical issue
3. The broader category or business impact

Keep queries concise but descriptive - they have a maximum length of {max_query_tokens} tokens. Each query will be embedded and used for semantic similarity search.

Respond with a JSON object containing a "queries" array with 1-3 query strings. Return ONLY valid JSON, no other text."""


def _build_query_generation_system_prompt(signal_type_examples: list[SignalTypeExample]) -> str:
    """Build the query generation system prompt, optionally including signal type examples."""
    if signal_type_examples:
        lines = [
            "Here are examples of signal types currently in the database, to help you understand what kinds of signals your queries might match against:\n"
        ]
        for ex in signal_type_examples:
            lines.append(f'- {ex.source_product} / {ex.source_type} (last seen: {ex.timestamp}): "{ex.content[:300]}"')
        examples_section = "\n".join(lines)
    else:
        examples_section = ""

    return QUERY_GENERATION_SYSTEM_PROMPT_TEMPLATE.format(
        examples_section=examples_section,
        max_query_tokens=MAX_QUERY_TOKENS,
    )


async def generate_search_queries(
    description: str,
    source_product: str,
    source_type: str,
    signal_type_examples: list[SignalTypeExample] | None = None,
) -> list[str]:
    """
    Use LLM to generate 1-3 search queries for finding related signals.
    Returns queries truncated to fit within embedding token limits.
    """

    system_prompt = _build_query_generation_system_prompt(signal_type_examples or [])

    user_prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}"""

    def validate(text: str) -> list[str]:
        data = json.loads(text)
        result = QueryGenerationResponse.model_validate(data)

        if len(result.queries) == 0:
            raise ValueError("LLM returned empty queries list")

        queries = result.queries[:MAX_QUERIES]
        return [truncate_query_to_token_limit(q) for q in queries]

    return await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.7,
    )


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


class LLMMatchFound(BaseModel):
    match_type: Literal["existing"]
    signal_id: str


class LLMNewGroup(BaseModel):
    match_type: Literal["new"]
    title: str
    summary: str


LLMMatchResponse = LLMMatchFound | LLMNewGroup


def _parse_match_response(data: dict) -> LLMMatchResponse:
    """Parse and validate LLM match response using discriminated union."""
    match_type = data.get("match_type")
    if match_type == "existing":
        return LLMMatchFound.model_validate(data)
    elif match_type == "new":
        return LLMNewGroup.model_validate(data)
    else:
        raise ValueError(f"Invalid match_type: {match_type}")


MATCHING_SYSTEM_PROMPT = """You are a signal grouping assistant. Your job is to determine if a new signal is related to an existing group of signals,
or if it should start a new group.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
Your task is to identify signals that are RELATED - they may be different signal types but connected by the same underlying cause, feature, or user journey.

IMPORTANT: Signals should be grouped if they are meaningfully related, not just superficially similar:
- An experiment reaching significance AND an error spike on the same feature SHOULD match (related by feature)
- A session behaviour anomaly AND an insight alert about the same user flow SHOULD match (related by user journey)
- Two "experiment reached significance" signals from DIFFERENT, unrelated experiments should NOT match
- Two signals about the SAME experiment (e.g., significance + follow-up analysis) SHOULD match

You will receive:
1. A new signal with its description and source information
2. Results from multiple search queries, each containing candidate signals with their IDs, descriptions, sources, and cosine distances

If a candidate signal from ANY query is related to the new signal, respond with the signal's ID:
{"match_type": "existing", "signal_id": "<the signal_id of the matching candidate>"}

If no candidate is related (or all queries returned no results), respond with:
{"match_type": "new", "title": "<short title for a new report>", "summary": "<1-2 sentence summary of what this signal group is about>"}

You must respond with valid JSON only, no other text."""


def _build_matching_prompt(
    description: str,
    source_product: str,
    source_type: str,
    queries: list[str],
    query_results: list[list[SignalCandidate]],
) -> str:
    prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}

SEARCH RESULTS:
"""

    for query_idx, (query, candidates) in enumerate(zip(queries, query_results)):
        prompt += f'\n--- Query {query_idx}: "{query}" ---\n'

        if not candidates:
            prompt += "(no results)\n"
        else:
            for c in candidates:
                prompt += f"""
- signal_id: {c.signal_id}
  distance: {c.distance:.4f}
  Source: {c.source_product} / {c.source_type}
  Description: {c.content}
"""

    return prompt


async def match_signal_with_llm(
    description: str,
    source_product: str,
    source_type: str,
    queries: list[str],
    query_results: list[list[SignalCandidate]],
) -> MatchResult:
    """
    Use LLM to determine if a new signal matches any existing report.

    Returns:
        ExistingReportMatch if a match is found, NewReportMatch otherwise
    """
    candidates_by_id: dict[str, SignalCandidate] = {}
    for candidates in query_results:
        for c in candidates:
            candidates_by_id[c.signal_id] = c

    user_prompt = _build_matching_prompt(description, source_product, source_type, queries, query_results)

    def validate(text: str) -> MatchResult:
        data = json.loads(text)
        result = _parse_match_response(data)

        if isinstance(result, LLMMatchFound):
            matched = candidates_by_id.get(result.signal_id)
            if matched is None:
                raise ValueError(f"signal_id {result.signal_id} not found in candidates")
            return ExistingReportMatch(report_id=matched.report_id)

        return NewReportMatch(title=result.title, summary=result.summary)

    return await call_llm(
        system_prompt=MATCHING_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.2,
    )


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


CONTINUE_AS_NEW_THRESHOLD = 20


async def _process_one_signal(inputs: EmitSignalInputs) -> str:
    """Shared signal processing logic used by both EmitSignalWorkflow and TeamSignalGroupingWorkflow."""
    from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow
    from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs

    with workflow.unsafe.imports_passed_through():
        from django.conf import settings

    signal_id = str(uuid.uuid4())

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

    if assign_result.promoted:
        try:
            await workflow.start_child_workflow(
                SignalReportSummaryWorkflow.run,
                SignalReportSummaryWorkflowInputs(team_id=inputs.team_id, report_id=assign_result.report_id),
                id=SignalReportSummaryWorkflow.workflow_id_for(inputs.team_id, assign_result.report_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                execution_timeout=timedelta(minutes=30),
            )
        except temporalio.exceptions.WorkflowAlreadyStartedError:
            pass

    return signal_id


@temporalio.workflow.defn(name="team-signal-grouping")
class TeamSignalGroupingWorkflow:
    """
    Long-running entity workflow that serializes signal grouping per team.

    One instance per team (workflow ID: team-signal-grouping-{team_id}). Signals arrive
    via @workflow.signal and are processed sequentially, eliminating race conditions
    where concurrent workflows could assign related signals to different reports.

    Uses continue_as_new after CONTINUE_AS_NEW_THRESHOLD signals to keep history bounded.
    """

    def __init__(self) -> None:
        self._signal_buffer: list[EmitSignalInputs] = []
        self._signals_processed: int = 0

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"team-signal-grouping-{team_id}"

    @temporalio.workflow.signal
    async def submit_signal(self, signal: EmitSignalInputs) -> None:
        self._signal_buffer.append(signal)

    @temporalio.workflow.run
    async def run(self, input: TeamSignalGroupingInput) -> None:
        self._signal_buffer.extend(input.pending_signals)

        while True:
            await workflow.wait_condition(lambda: len(self._signal_buffer) > 0)
            signal = self._signal_buffer.pop(0)

            try:
                await _process_one_signal(signal)
            except Exception:
                logger.exception(
                    "Failed to process signal",
                    team_id=input.team_id,
                    source_product=signal.source_product,
                    source_type=signal.source_type,
                    source_id=signal.source_id,
                )

            self._signals_processed += 1
            if self._signals_processed >= CONTINUE_AS_NEW_THRESHOLD:
                workflow.continue_as_new(
                    TeamSignalGroupingInput(
                        team_id=input.team_id,
                        pending_signals=list(self._signal_buffer),
                    )
                )
