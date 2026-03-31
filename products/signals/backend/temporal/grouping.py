import os
import json
import uuid
import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional, cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import numpy as np
import structlog
import temporalio
from pydantic import BaseModel, Field
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.workflow import ParentClosePolicy

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast

from posthog.api.embedding_worker import async_generate_embedding, emit_embedding_request
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry
from products.signals.backend.temporal.llm import MAX_QUERY_TOKENS, call_llm, truncate_query_to_token_limit
from products.signals.backend.temporal.summary import (
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    SignalReportSummaryWorkflow,
    fetch_signals_for_report_activity,
)
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ExistingReportMatch,
    MatchedMetadata,
    MatchResult,
    NewReportMatch,
    NoMatchMetadata,
    ReportContext,
    SignalCandidate,
    SignalData,
    SignalReportSummaryWorkflowInputs,
    SignalTypeExample,
    SpecificityMetadata,
    TeamSignalGroupingInput,
)
from products.signals.backend.utils import EMBEDDING_MODEL, soft_delete_report_signals

logger = structlog.get_logger(__name__)

WEIGHT_THRESHOLD = float(os.getenv("SIGNAL_WEIGHT_THRESHOLD", "1.0"))
MAX_QUERIES = 3


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
        response = await async_generate_embedding(team, input.content, model=EMBEDDING_MODEL.value)
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
        return [truncate_query_to_token_limit(q) for q in result.queries]

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
              AND NOT JSONExtractBool(metadata, 'deleted')
            ORDER BY distance ASC
            LIMIT {limit}
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


class MatchFound(BaseModel):
    reason: str
    match_type: Literal["existing"]
    signal_id: str
    query_index: int


class NewGroup(BaseModel):
    reason: str
    match_type: Literal["new"]
    title: str
    summary: str


MatchResponse = MatchFound | NewGroup


def _parse_match_response(data: dict) -> MatchResponse:
    """Parse and validate match response using discriminated union."""
    match_type = data.get("match_type")
    if match_type == "existing":
        return MatchFound.model_validate(data)
    elif match_type == "new":
        return NewGroup.model_validate(data)
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
2. Discovery strength: how many independent search queries found signals in each existing group (higher = stronger evidence)
3. Results from multiple search queries, each with candidate signals annotated with their group title and group size

IMPORTANT — use group context when deciding:
- Each candidate belongs to a group. The group title tells you the group's overall theme.
- Match the new signal to a GROUP's theme, not just to an individual candidate signal.
- A candidate that shares a keyword with the new signal but belongs to an unrelated group should NOT be matched.
- Groups found by multiple independent queries are more likely genuinely related.

If a candidate signal from ANY query is related to the new signal AND its group theme aligns, respond with:
{
  "reason": "<Brief, less than 100 character sentence explaining what connects the signal to the group>",
  "match_type": "existing",
  "signal_id": "<the signal_id of the matching candidate>",
  "query_index": <0-based index of the query that surfaced this candidate>
}

If no candidate is related (or all queries returned no results), respond with:
{
  "reason": "<Brief, less than 100 character sentence explaining why none of the candidates are related>",
  "match_type": "new",
  "title": "<short title for a new report>",
  "summary": "<1-2 sentence summary of what this signal group is about>"
}

IMPORTANT: The "reason" field MUST be the first key in your JSON response. Write your reasoning BEFORE making the match decision.

You must respond with valid JSON only, no other text."""


SPECIFICITY_CHECK_SYSTEM_PROMPT = """You are a senior engineer reviewing whether a group of signals belongs in a single pull request.

You will receive:
1. A group of existing signals (the current report)
2. A new signal being proposed for addition

Your job:
1. Write a single PR title (max 70 chars) that covers ALL signals in the group INCLUDING the new one.
2. Judge: is this PR title specific enough that one engineer could ship it in a single pull request?

A SPECIFIC PR title targets one feature, one bug, one component, or one tightly-scoped change:
- "Fix date picker timezone handling in insights" — SPECIFIC (one component, one bug type)
- "Add K8s liveness probe and fix feature flag caching" — SPECIFIC (one infra concern, tightly related)
- "Fix funnel conversion calculation for time-based bins" — SPECIFIC (one feature, one issue)

A VAGUE PR title is a catch-all that no single engineer would take on:
- "Fix various PostHog AI issues" — VAGUE (multiple unrelated areas)
- "Multiple workflow and integration improvements" — VAGUE (different systems)
- "Address feature flag and authentication concerns" — VAGUE (unrelated domains)

IMPORTANT: Err on the side of REJECTING. A good PR addresses ONE concern, even if that concern has multiple symptoms.

Red flags that the group is too broad:
- You need words like "various", "multiple", "and" (connecting unrelated things), or "improvements"
- The signals share a keyword (e.g. "workflows", "flags", "Next.js") but address different problems
- You'd assign the signals to different engineers based on expertise
- The PR touches multiple unrelated systems or components

Respond with valid JSON only:
{"pr_title": "...", "specific_enough": true/false, "reason": "..."}"""


class SpecificityResult(BaseModel):
    pr_title: str
    specific_enough: bool
    reason: str


MAX_SIGNALS_IN_SPECIFICITY_CONTEXT = 8


def _build_matching_prompt(
    description: str,
    source_product: str,
    source_type: str,
    queries: list[str],
    query_results: list[list[SignalCandidate]],
    report_contexts: dict[str, ReportContext],
) -> str:
    """Build matching prompt with group titles and multi-query agreement summary."""
    report_query_hits: dict[str, set[int]] = defaultdict(set)
    for query_idx, candidates in enumerate(query_results):
        for c in candidates:
            report_query_hits[c.report_id].add(query_idx)

    prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}

DISCOVERY STRENGTH (groups found by multiple independent queries are more likely related):
"""
    for report_id, query_indices in sorted(report_query_hits.items(), key=lambda x: -len(x[1])):
        ctx = report_contexts.get(report_id)
        title = ctx.title if ctx else "(untitled)"
        size = ctx.signal_count if ctx else 0
        prompt += f'- "{title}" ({size} signal{"s" if size != 1 else ""}): found by {len(query_indices)}/{len(queries)} queries\n'

    prompt += "\nSEARCH RESULTS:\n"
    for query_idx, (query, candidates) in enumerate(zip(queries, query_results)):
        prompt += f'\n--- Query {query_idx}: "{query}" ---\n'

        if not candidates:
            prompt += "(no results)\n"
        else:
            for c in candidates:
                ctx = report_contexts.get(c.report_id)
                title = ctx.title if ctx else "(untitled)"
                size = ctx.signal_count if ctx else 0
                prompt += f"""- signal_id: {c.signal_id}
  distance: {c.distance:.4f}
  Source: {c.source_product} / {c.source_type}
  Group: "{title}" ({size} signal{"s" if size != 1 else ""})
  Description: {c.content}
"""

    return prompt


def _build_specificity_prompt(
    new_signal_description: str,
    new_signal_source_product: str,
    new_signal_source_type: str,
    report_title: str,
    group_signals: list[SignalData],
) -> str:
    """Build prompt for the PR-specificity verification gate."""
    prompt = f"""EXISTING GROUP:
- Title: {report_title or "(untitled)"}
- Signals ({len(group_signals)} total):
"""
    for i, sig in enumerate(group_signals[:MAX_SIGNALS_IN_SPECIFICITY_CONTEXT]):
        prompt += f"""
  Signal {i + 1}:
  - Source: {sig.source_product} / {sig.source_type}
  - Description: {sig.content[:500]}
"""
    remaining = len(group_signals) - MAX_SIGNALS_IN_SPECIFICITY_CONTEXT
    if remaining > 0:
        prompt += f"\n  ... and {remaining} more signals\n"

    prompt += f"""
NEW SIGNAL PROPOSED FOR ADDITION:
- Source: {new_signal_source_product} / {new_signal_source_type}
- Description: {new_signal_description}

Write a PR title covering ALL the above signals (existing + new), then judge if it's specific enough for one pull request."""
    return prompt


async def match_signal_to_report(
    description: str,
    source_product: str,
    source_type: str,
    queries: list[str],
    query_results: list[list[SignalCandidate]],
    report_contexts: dict[str, ReportContext],
) -> MatchResult:
    """
    Determine if a new signal matches an existing report or needs a new one.

    Returns:
        ExistingReportMatch if a match is found, NewReportMatch otherwise
    """
    candidates_by_id: dict[str, SignalCandidate] = {}
    for candidates in query_results:
        for c in candidates:
            candidates_by_id[c.signal_id] = c

    user_prompt = _build_matching_prompt(
        description, source_product, source_type, queries, query_results, report_contexts
    )

    def validate(text: str) -> MatchResult:
        data = json.loads(text)
        result = _parse_match_response(data)

        if isinstance(result, MatchFound):
            matched = candidates_by_id.get(result.signal_id)
            if matched is None:
                raise ValueError(f"signal_id {result.signal_id} not found in candidates")
            if result.query_index < 0 or result.query_index >= len(queries):
                raise ValueError(f"query_index {result.query_index} out of range (0-{len(queries) - 1})")
            return ExistingReportMatch(
                report_id=matched.report_id,
                match_metadata=MatchedMetadata(
                    parent_signal_id=result.signal_id,
                    match_query=queries[result.query_index],
                    reason=result.reason,
                ),
            )

        return NewReportMatch(
            title=result.title,
            summary=result.summary,
            match_metadata=NoMatchMetadata(
                reason=result.reason,
                rejected_signal_ids=list(candidates_by_id.keys()),
            ),
        )

    return await call_llm(
        system_prompt=MATCHING_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.2,
    )


@dataclass
class MatchSignalToReportInput:
    description: str
    source_product: str
    source_type: str
    queries: list[str]
    query_results: list[list[SignalCandidate]]
    report_contexts: dict[str, ReportContext]


@temporalio.activity.defn
async def match_signal_to_report_activity(input: MatchSignalToReportInput) -> MatchResult:
    """Determine if a new signal matches an existing report or needs a new one."""
    try:
        result = await match_signal_to_report(
            description=input.description,
            source_product=input.source_product,
            source_type=input.source_type,
            queries=input.queries,
            query_results=input.query_results,
            report_contexts=input.report_contexts,
        )
        total_candidates = sum(len(r) for r in input.query_results)
        logger.debug(
            f"Match result: matched={isinstance(result, ExistingReportMatch)}",
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
class FetchReportContextsInput:
    team_id: int
    report_ids: list[str]


@dataclass
class FetchReportContextsOutput:
    contexts: dict[str, ReportContext]


@temporalio.activity.defn
async def fetch_report_contexts_activity(input: FetchReportContextsInput) -> FetchReportContextsOutput:
    """Fetch lightweight context (title, signal count) for reports from Postgres."""
    if not input.report_ids:
        return FetchReportContextsOutput(contexts={})

    try:
        reports = SignalReport.objects.filter(team_id=input.team_id, id__in=input.report_ids).values_list(
            "id", "title", "signal_count"
        )
        contexts: dict[str, ReportContext] = {}
        async for report_id, title, signal_count in reports:
            rid = str(report_id)
            contexts[rid] = ReportContext(
                report_id=rid,
                title=title or "(untitled)",
                signal_count=signal_count,
            )
        logger.debug(
            f"Fetched contexts for {len(contexts)}/{len(input.report_ids)} reports",
            requested=len(input.report_ids),
            found=len(contexts),
        )
        return FetchReportContextsOutput(contexts=contexts)
    except Exception as e:
        logger.exception(f"Failed to fetch report contexts: {e}")
        raise


@dataclass
class VerifyMatchSpecificityInput:
    team_id: int
    report_id: str
    report_title: str
    new_signal_description: str
    new_signal_source_product: str
    new_signal_source_type: str
    group_signals: list[SignalData]


@dataclass
class VerifyMatchSpecificityOutput:
    pr_title: str
    specific_enough: bool
    reason: str


async def verify_match_specificity(
    new_signal_description: str,
    new_signal_source_product: str,
    new_signal_source_type: str,
    report_title: str,
    group_signals: list[SignalData],
) -> VerifyMatchSpecificityOutput:
    """Verify that adding a signal to a group produces a specific-enough PR title."""
    specificity_prompt = _build_specificity_prompt(
        new_signal_description=new_signal_description,
        new_signal_source_product=new_signal_source_product,
        new_signal_source_type=new_signal_source_type,
        report_title=report_title,
        group_signals=group_signals,
    )

    specificity = await call_llm(
        system_prompt=SPECIFICITY_CHECK_SYSTEM_PROMPT,
        user_prompt=specificity_prompt,
        validate=lambda text: SpecificityResult.model_validate_json(text),
        temperature=0.2,
    )

    return VerifyMatchSpecificityOutput(
        pr_title=specificity.pr_title,
        specific_enough=specificity.specific_enough,
        reason=specificity.reason,
    )


@temporalio.activity.defn
async def verify_match_specificity_activity(input: VerifyMatchSpecificityInput) -> VerifyMatchSpecificityOutput:
    """Verify that adding a signal to a group produces a specific-enough PR title."""
    try:
        result = await verify_match_specificity(
            new_signal_description=input.new_signal_description,
            new_signal_source_product=input.new_signal_source_product,
            new_signal_source_type=input.new_signal_source_type,
            report_title=input.report_title,
            group_signals=input.group_signals,
        )

        logger.debug(
            f"Specificity check for report {input.report_id}: "
            f'pr_title="{result.pr_title}", specific_enough={result.specific_enough}',
            team_id=input.team_id,
            report_id=input.report_id,
            pr_title=result.pr_title,
            specific_enough=result.specific_enough,
            reason=result.reason,
        )
        return result
    except Exception as e:
        logger.exception(
            f"Failed to verify match specificity for report {input.report_id}: {e}",
            team_id=input.team_id,
            report_id=input.report_id,
        )
        raise


@dataclass
class AssignAndEmitSignalInput:
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
    timestamp: Optional[datetime] = None
    updated_title: Optional[str] = None


@dataclass
class AssignAndEmitSignalOutput:
    report_id: str
    promoted: bool
    timestamp: datetime
    run_count: int


@temporalio.activity.defn
async def assign_and_emit_signal_activity(input: AssignAndEmitSignalInput) -> AssignAndEmitSignalOutput:
    match_result = input.match_result

    def do_assign_and_emit() -> tuple[str, bool, datetime, bool, int]:
        """Returns (report_id, promoted, timestamp, matched_deleted_report, run_count)."""
        with transaction.atomic():
            promoted = False

            if isinstance(match_result, ExistingReportMatch):
                report = SignalReport.objects.select_for_update().get(id=match_result.report_id, team_id=input.team_id)
                # Soft-deleted reports shouldn't receive new signals at all. Generally, these
                # won't be matched-to (since the associated signals are also deleted), but
                # if a report is deleted while a signal that would match it is in-flight,
                # this can happen. In these cases we skip the weight/count update and skip
                # promotion, but we still emit the signal to ClickHouse, marked as deleted
                # in metadata.
                #
                # We also soft-delete all stale signals for the deleted report (outside the
                # transaction) so they stop showing up in semantic search and attracting
                # future signals to the dead report.
                if report.status == SignalReport.Status.DELETED:
                    report_id = str(report.id)
                    ts = input.timestamp or timezone.now()
                    metadata = {
                        "source_product": input.source_product,
                        "source_type": input.source_type,
                        "source_id": input.source_id,
                        "weight": input.weight,
                        "report_id": report_id,
                        "extra": input.extra,
                        "deleted": True,
                    }
                    metadata["match_metadata"] = asdict(match_result.match_metadata)
                    emit_embedding_request(
                        content=input.description,
                        team_id=input.team_id,
                        product="signals",
                        document_type="signal",
                        rendering="plain",
                        document_id=input.signal_id,
                        models=[m.value for m in EmbeddingModelName],
                        timestamp=ts,
                        metadata=metadata,
                    )
                    return report_id, False, ts, True, report.run_count
                report.total_weight += input.weight
                report.signal_count += 1
                update_fields = ["total_weight", "signal_count", "updated_at"]
                if input.updated_title:
                    report.title = input.updated_title
                    update_fields.append("title")
                report.save(update_fields=update_fields)
            else:
                report = SignalReport.objects.create(
                    team_id=input.team_id,
                    status=SignalReport.Status.POTENTIAL,
                    total_weight=input.weight,
                    signal_count=1,
                    title=match_result.title,
                    summary=match_result.summary,
                )

            # - SUPPRESSED reports gather signals indefinitely but are never promoted.
            # - POTENTIAL reports are promoted once signal_count >= signals_at_run (snooze gate;
            # signals_at_run defaults to 0 so fresh reports always pass) and weight threshold is met.
            # - READY reports are re-promoted under the same gate so the summary workflow can
            # regenerate the report with the additional signals, keeping it meaningful as
            # new evidence accumulates.
            if (
                report.status in (SignalReport.Status.POTENTIAL, SignalReport.Status.READY)
                and report.total_weight >= WEIGHT_THRESHOLD
                and report.signal_count >= report.signals_at_run
            ):
                updated_fields = report.transition_to(SignalReport.Status.CANDIDATE)
                report.save(update_fields=updated_fields)
                promoted = True

            report_id = str(report.id)

            metadata = {
                "source_product": input.source_product,
                "source_type": input.source_type,
                "source_id": input.source_id,
                "weight": input.weight,
                "report_id": report_id,
                "extra": input.extra,
            }

            metadata["match_metadata"] = asdict(match_result.match_metadata)

            ts = input.timestamp or timezone.now()

            emit_embedding_request(
                content=input.description,
                team_id=input.team_id,
                product="signals",
                document_type="signal",
                rendering="plain",
                document_id=input.signal_id,
                models=[m.value for m in EmbeddingModelName],
                timestamp=ts,
                metadata=metadata,
            )

            return report_id, promoted, ts, False, report.run_count

    try:
        report_id, promoted, ts, matched_deleted, run_count = await database_sync_to_async(
            do_assign_and_emit, thread_sensitive=False
        )()

        # If we matched a deleted report, soft-delete all its stale signals in ClickHouse.
        # This prevents data corruption where non-deleted signals for a deleted report
        # keep attracting new signals into the dead group.
        if matched_deleted:
            team = await Team.objects.aget(pk=input.team_id)
            await database_sync_to_async(soft_delete_report_signals, thread_sensitive=False)(
                report_id=report_id,
                team_id=input.team_id,
                team=team,
            )
            logger.info(
                "Soft-deleted stale signals for deleted report encountered during grouping",
                report_id=report_id,
                team_id=input.team_id,
                signal_id=input.signal_id,
            )

        logger.debug(
            f"Assigned and emitted signal to report {report_id}",
            report_id=report_id,
            team_id=input.team_id,
            signal_id=input.signal_id,
            promoted=promoted,
            is_new_report=isinstance(match_result, NewReportMatch),
        )
        return AssignAndEmitSignalOutput(report_id=report_id, promoted=promoted, timestamp=ts, run_count=run_count)
    except Exception as e:
        logger.exception(
            f"Failed to assign/emit signal: {e}",
            team_id=input.team_id,
            signal_id=input.signal_id,
        )
        raise


@dataclass
class WaitForClickHouseSignal:
    signal_id: str
    timestamp: datetime


@dataclass
class WaitForClickHouseInput:
    team_id: int
    signals: list[WaitForClickHouseSignal]
    max_wait_time_seconds: int = 3600


WAIT_POLL_INTERVAL_SECONDS = 10


@temporalio.activity.defn
async def wait_for_signal_in_clickhouse_activity(input: WaitForClickHouseInput) -> None:
    """Poll ClickHouse until all emitted signals appear, or give up after max_wait_time_seconds.

    Filters on inserted_at >= (now - 30 minutes) to avoid matching stale rows from a
    previous emission of the same document_id (e.g. deleted then reingested). The window
    is generous because signals are emitted during the sequential phase before this
    activity starts, so early signals may already be minutes old.
    """
    if not input.signals:
        return

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

    for attempt in range(max_attempts):
        temporalio.activity.heartbeat(attempt)

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

    logger.warning(
        f"Not all signals found in ClickHouse after {input.max_wait_time_seconds}s, proceeding anyway",
        signal_ids=signal_ids,
        team_id=input.team_id,
    )


CONTINUE_AS_NEW_THRESHOLD = 20
BATCH_SIZE = 5
BATCH_DEBOUNCE_SECONDS = 5
TYPE_EXAMPLES_CACHE_TTL = timedelta(minutes=5)


@dataclass
class _ProcessedBatchSignal:
    """A signal processed earlier in the current batch, used to augment later signals' candidates."""

    signal_id: str
    report_id: str
    content: str
    source_product: str
    source_type: str
    embedding: list[float]


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Compute cosine distance between two embedding vectors."""
    a_arr = np.asarray(a)
    b_arr = np.asarray(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def _augment_candidates_with_batch(
    query_embeddings: list[list[float]],
    ch_candidates_per_query: list[list[SignalCandidate]],
    processed_signals: list[_ProcessedBatchSignal],
    limit: int = 10,
) -> list[list[SignalCandidate]]:
    """Augment CH search results with earlier-in-batch signals via local cosine distance."""
    if not processed_signals:
        return ch_candidates_per_query

    augmented = []
    for query_emb, ch_candidates in zip(query_embeddings, ch_candidates_per_query):
        candidates = list(ch_candidates)
        worst_distance = candidates[-1].distance if candidates else float("inf")

        for ps in processed_signals:
            dist = _cosine_distance(query_emb, ps.embedding)
            if len(candidates) < limit or dist < worst_distance:
                candidates.append(
                    SignalCandidate(
                        signal_id=ps.signal_id,
                        report_id=ps.report_id,
                        content=ps.content,
                        source_product=ps.source_product,
                        source_type=ps.source_type,
                        distance=dist,
                    )
                )

        candidates.sort(key=lambda c: c.distance)
        augmented.append(candidates[:limit])

    return augmented


async def _process_signal_batch(
    batch: list[EmitSignalInputs],
    cached_type_examples: Optional[FetchSignalTypeExamplesOutput] = None,
) -> tuple[int, FetchSignalTypeExamplesOutput]:
    """
    Process a batch of signals with parallel preparation (steps 1-4) and sequential
    matching/assignment (steps 5-7). Returns (dropped_count, type_examples) — the
    caller can cache the type_examples for subsequent batches.

    Earlier signals in the batch are injected into later signals' candidate sets via
    local cosine distance comparison, eliminating the need for per-signal CH waits
    within a batch.
    """
    team_id = batch[0].team_id
    # Purely defensive
    if not all(signal.team_id == team_id for signal in batch):
        raise ValueError("All signals in a batch must belong to the same team")
    dropped = 0

    # === PARALLEL PHASE (steps 1-4) ===

    # Step 1a: Fetch type examples if not cached (needed by query gen)
    if cached_type_examples is not None:
        type_examples_result = cached_type_examples
    else:
        type_examples_result = await workflow.execute_activity(
            fetch_signal_type_examples_activity,
            FetchSignalTypeExamplesInput(team_id=team_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    # Step 1b: Embed all signals + generate search queries in parallel
    # (query gen needs type examples but NOT the signal embeddings)
    step1b_results = await asyncio.gather(
        *[
            workflow.execute_activity(
                get_embedding_activity,
                GenerateEmbeddingInput(team_id=team_id, content=s.description),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            for s in batch
        ],
        *[
            workflow.execute_activity(
                generate_search_queries_activity,
                GenerateSearchQueriesInput(
                    description=s.description,
                    source_product=s.source_product,
                    source_type=s.source_type,
                    signal_type_examples=type_examples_result.examples,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            for s in batch
        ],
    )
    signal_embeddings = cast(list[GenerateEmbeddingOutput], step1b_results[: len(batch)])
    query_gen_results = cast(list[GenerateSearchQueriesOutput], step1b_results[len(batch) :])

    # Step 3: Embed all queries across all signals (flatten → parallel embed)
    all_queries_flat: list[tuple[int, str]] = []
    for sig_idx, qr in enumerate(query_gen_results):
        for q in qr.queries:
            all_queries_flat.append((sig_idx, q))

    all_query_embeddings: list[GenerateEmbeddingOutput] = list(
        await asyncio.gather(
            *[
                workflow.execute_activity(
                    get_embedding_activity,
                    GenerateEmbeddingInput(team_id=team_id, content=q_text),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for _, q_text in all_queries_flat
            ]
        )
    )

    # Step 4: Semantic search for all queries (all parallel)
    all_search_results: list[RunSignalSemanticSearchOutput] = list(
        await asyncio.gather(
            *[
                workflow.execute_activity(
                    run_signal_semantic_search_activity,
                    RunSignalSemanticSearchInput(team_id=team_id, embedding=emb.embedding, limit=10),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for emb in all_query_embeddings
            ]
        )
    )

    # Regroup flat results back to per-signal
    # Each query becomes an embedding vector for lookup
    type EmbeddingVector = list[float]
    # For each new signal, we generate a number N of query strings
    type SignalQueries = list[str]
    # For each new signal, we generate an embedding for each query (so N embeddings)
    type SignalQueryEmbeddings = list[EmbeddingVector]
    # For each new signal, for each query, we get a list of M candidates back (10 at time of writing)
    type SignalQueryResults = list[SignalCandidate]
    # For each new signal, we run each query, so we get N * M total candidates for matching (although we fold down overlap across queries)
    type SignalMatchCandidates = list[SignalQueryResults]
    per_signal_queries: list[SignalQueries] = [[] for _ in batch]
    per_signal_query_embeddings: list[SignalQueryEmbeddings] = [[] for _ in batch]
    per_signal_ch_results: list[SignalMatchCandidates] = [[] for _ in batch]
    for flat_idx, (sig_idx, q_text) in enumerate(all_queries_flat):
        per_signal_queries[sig_idx].append(q_text)
        per_signal_query_embeddings[sig_idx].append(all_query_embeddings[flat_idx].embedding)
        per_signal_ch_results[sig_idx].append(all_search_results[flat_idx].candidates)

    # Step 4.5: Fetch report contexts for all CH candidates (group-aware matching)
    all_candidate_report_ids = list({c.report_id for results in all_search_results for c in results.candidates})
    report_contexts_result: FetchReportContextsOutput = await workflow.execute_activity(
        fetch_report_contexts_activity,
        FetchReportContextsInput(team_id=team_id, report_ids=all_candidate_report_ids),
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )
    report_contexts: dict[str, ReportContext] = report_contexts_result.contexts

    # === SEQUENTIAL PHASE (steps 5-7) ===
    processed_batch_signals: list[_ProcessedBatchSignal] = []
    promoted_reports: dict[str, tuple[SignalReportSummaryWorkflowInputs, int]] = {}
    emitted_signals: list[tuple[str, AssignAndEmitSignalOutput]] = []

    for i, signal in enumerate(batch):
        signal_id = str(uuid.uuid4())
        try:
            # Augment CH candidates with earlier-in-batch signals
            augmented_results = _augment_candidates_with_batch(
                per_signal_query_embeddings[i],
                per_signal_ch_results[i],
                processed_batch_signals,
                limit=10,
            )

            # Step 5: Group-aware LLM match
            match_result = await workflow.execute_activity(
                match_signal_to_report_activity,
                MatchSignalToReportInput(
                    description=signal.description,
                    source_product=signal.source_product,
                    source_type=signal.source_type,
                    queries=per_signal_queries[i],
                    query_results=augmented_results,
                    report_contexts=report_contexts,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )

            # Step 5.5: PR-specificity verification for existing matches
            updated_title: Optional[str] = None

            if isinstance(match_result, ExistingReportMatch):
                report_ctx = report_contexts.get(match_result.report_id)
                report_title = report_ctx.title if report_ctx else ""

                group_signals_result: FetchSignalsForReportOutput = await workflow.execute_activity(
                    fetch_signals_for_report_activity,
                    FetchSignalsForReportInput(team_id=team_id, report_id=match_result.report_id),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                specificity_result: VerifyMatchSpecificityOutput = await workflow.execute_activity(
                    verify_match_specificity_activity,
                    VerifyMatchSpecificityInput(
                        team_id=team_id,
                        report_id=match_result.report_id,
                        report_title=report_title,
                        new_signal_description=signal.description,
                        new_signal_source_product=signal.source_product,
                        new_signal_source_type=signal.source_type,
                        group_signals=group_signals_result.signals,
                    ),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )

                specificity_meta = SpecificityMetadata(
                    pr_title=specificity_result.pr_title,
                    specific_enough=specificity_result.specific_enough,
                    reason=specificity_result.reason,
                )

                if specificity_result.specific_enough:
                    updated_title = specificity_result.pr_title
                    match_result.match_metadata.specificity = specificity_meta
                else:
                    match_result = NewReportMatch(
                        title=signal.description.split("\n")[0],
                        summary=f"Split from group: {report_title}",
                        match_metadata=NoMatchMetadata(
                            reason=f'PR-specificity rejected: "{specificity_result.pr_title}" — {specificity_result.reason}',
                            specificity_rejection=specificity_meta,
                        ),
                    )

            # Step 6: Assign + emit
            assign_result: AssignAndEmitSignalOutput = await workflow.execute_activity(
                assign_and_emit_signal_activity,
                AssignAndEmitSignalInput(
                    team_id=signal.team_id,
                    signal_id=signal_id,
                    description=signal.description,
                    weight=signal.weight,
                    source_product=signal.source_product,
                    source_type=signal.source_type,
                    source_id=signal.source_id,
                    extra=signal.extra,
                    embedding=signal_embeddings[i].embedding,
                    match_result=match_result,
                    updated_title=updated_title,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Track for augmenting later signals in the batch
            processed_batch_signals.append(
                _ProcessedBatchSignal(
                    signal_id=signal_id,
                    report_id=assign_result.report_id,
                    content=signal.description,
                    source_product=signal.source_product,
                    source_type=signal.source_type,
                    embedding=signal_embeddings[i].embedding,
                )
            )
            emitted_signals.append((signal_id, assign_result))

            # Update local report_contexts so later signals in the batch see this report
            if isinstance(match_result, ExistingReportMatch):
                old_ctx = report_contexts.get(assign_result.report_id)
                report_contexts[assign_result.report_id] = ReportContext(
                    report_id=assign_result.report_id,
                    title=updated_title or (old_ctx.title if old_ctx else ""),
                    signal_count=(old_ctx.signal_count if old_ctx else 0) + 1,
                )
            else:
                report_contexts[assign_result.report_id] = ReportContext(
                    report_id=assign_result.report_id,
                    title=match_result.title,
                    signal_count=1,
                )

            if assign_result.promoted:
                promoted_reports[assign_result.report_id] = (
                    SignalReportSummaryWorkflowInputs(team_id=signal.team_id, report_id=assign_result.report_id),
                    assign_result.run_count,
                )

        except Exception:
            dropped += 1
            workflow.logger.exception(
                "Failed to process signal in batch",
                team_id=team_id,
                source_product=signal.source_product,
                source_type=signal.source_type,
                source_id=signal.source_id,
            )

    # Step 7: Wait for all emitted signals to land in CH so the next batch can find them
    if emitted_signals:
        await workflow.execute_activity(
            wait_for_signal_in_clickhouse_activity,
            WaitForClickHouseInput(
                team_id=team_id,
                signals=[
                    WaitForClickHouseSignal(signal_id=sid, timestamp=result.timestamp)
                    for sid, result in emitted_signals
                ],
                max_wait_time_seconds=3600,
            ),
            start_to_close_timeout=timedelta(hours=1, minutes=5),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    # Spawn summary workflows after CH wait so they can find the signals.
    for report_input, run_count in promoted_reports.values():
        try:
            base_id = SignalReportSummaryWorkflow.workflow_id_for(report_input.team_id, report_input.report_id)
            # Include run_count in the workflow ID to allow re-generating READY reports when enough new signals arrive,
            # as without it ALLOW_DUPLICATE_FAILED_ONLY will prevent the re-report from starting
            workflow_id = base_id if run_count == 0 else f"{base_id}:run-{run_count + 1}"
            # Concurrent report generation of the same report can't happen, as the promotion gate only allows
            # POTENTIAL and READY, so IN_PROGRESS reports are never re-promoted.
            await workflow.start_child_workflow(
                SignalReportSummaryWorkflow.run,
                report_input,
                id=workflow_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                execution_timeout=timedelta(hours=1),
            )
        except temporalio.exceptions.WorkflowAlreadyStartedError:
            pass

    return dropped, type_examples_result


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
        self._cached_type_examples: Optional[FetchSignalTypeExamplesOutput] = None
        self._type_examples_fetched_at: Optional[datetime] = None
        meter = workflow.metric_meter()
        self._signals_received_counter = meter.create_counter(
            "signals_grouping_signals_received",
            "Total number of signals received for grouping",
        )
        self._buffer_size_gauge = meter.create_gauge(
            "signals_grouping_buffer_size",
            "Current number of signals buffered for processing",
        )
        self._signals_dropped_counter = meter.create_counter(
            "signals_grouping_signals_dropped",
            "Total number of signals dropped due to processing failure",
        )

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"team-signal-grouping-{team_id}"

    @temporalio.workflow.signal
    async def submit_signal(self, signal: EmitSignalInputs) -> None:
        # TODO - add some kind of limiting here, to prevent this growing forever
        self._signal_buffer.append(signal)
        self._signals_received_counter.add(1)
        self._buffer_size_gauge.set(len(self._signal_buffer))

    @temporalio.workflow.run
    async def run(self, input: TeamSignalGroupingInput) -> None:
        self._signal_buffer.extend(input.pending_signals)
        self._buffer_size_gauge.set(len(self._signal_buffer))

        while True:
            await workflow.wait_condition(lambda: len(self._signal_buffer) > 0)

            # Debounce: wait briefly for more signals to accumulate
            if len(self._signal_buffer) < BATCH_SIZE:
                try:
                    await workflow.wait_condition(
                        lambda: len(self._signal_buffer) >= BATCH_SIZE,
                        timeout=timedelta(seconds=BATCH_DEBOUNCE_SECONDS),
                    )
                except TimeoutError:
                    pass

            batch: list[EmitSignalInputs] = []
            while self._signal_buffer and len(batch) < BATCH_SIZE:
                batch.append(self._signal_buffer.pop(0))
            self._buffer_size_gauge.set(len(self._signal_buffer))

            # Invalidate type examples cache if stale
            now = workflow.now()
            cached = self._cached_type_examples
            if (
                self._type_examples_fetched_at is not None
                and (now - self._type_examples_fetched_at) > TYPE_EXAMPLES_CACHE_TTL
            ):
                cached = None

            try:
                dropped, type_examples = await _process_signal_batch(batch, cached_type_examples=cached)
                self._cached_type_examples = type_examples
                self._type_examples_fetched_at = self._type_examples_fetched_at if cached is not None else now
                self._signals_dropped_counter.add(dropped)
            except Exception:
                # Parallel phase failed — all signals in batch dropped
                self._signals_dropped_counter.add(len(batch))
                workflow.logger.exception(
                    "Failed to process signal batch",
                    team_id=input.team_id,
                    batch_size=len(batch),
                )

            self._signals_processed += len(batch)

            if self._signals_processed >= CONTINUE_AS_NEW_THRESHOLD:
                workflow.continue_as_new(
                    TeamSignalGroupingInput(
                        team_id=input.team_id,
                        pending_signals=list(self._signal_buffer),
                    )
                )
