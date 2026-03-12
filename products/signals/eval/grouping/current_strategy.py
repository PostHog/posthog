"""
Current production grouping strategy, adapted for in-memory use.

Replicates the exact production flow:
1. Generate 1-3 search queries via LLM
2. Embed each query
3. Cosine search in-memory store
4. LLM match decision (existing report or new group)

Prompts and validation logic are copied from the production codebase because
grouping.py has top-level Django/Temporal imports that prevent standalone use.
Keep in sync with the source files noted below.
"""

import json
import uuid
import logging
from typing import Literal

from harness import (
    EmbeddingCache,
    GroupingDecision,
    InMemorySignalStore,
    SignalCandidate,
    SignalTypeExample,
    TestSignal,
    call_llm_standalone,
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_QUERY_TOKENS = 2048


# --- Query generation ---
# Source: products/signals/backend/temporal/grouping.py (QueryGenerationResponse, QUERY_GENERATION_SYSTEM_PROMPT_TEMPLATE, _build_query_generation_system_prompt)


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


# --- Matching ---
# Source: products/signals/backend/temporal/grouping.py (MatchFound, NewGroup, MATCHING_SYSTEM_PROMPT, _build_matching_prompt)


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

If a candidate signal from ANY query is related to the new signal, respond with:
{
  "reason": "<Brief, less than 100 character sentence explaining what connects the two signals>",
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


# --- Strategy implementation ---


class CurrentStrategy:
    """Replicates the production grouping strategy in-memory."""

    async def assign_signal(
        self,
        signal: TestSignal,
        signal_embedding: list[float],
        store: InMemorySignalStore,
        embedding_cache: EmbeddingCache,
    ) -> GroupingDecision:
        # If no signals in store yet, always create a new group
        if store.signal_count == 0:
            report_id = str(uuid.uuid4())
            return GroupingDecision(
                report_id=report_id,
                is_new=True,
                title=signal.content[:75],
                reason="First signal, creating new group",
            )

        # Step 1: Get type examples from store
        type_examples = store.get_type_examples()

        # Step 2: Generate search queries via LLM
        system_prompt = _build_query_generation_system_prompt(type_examples)
        user_prompt = f"""NEW SIGNAL:
- Source: {signal.source_product} / {signal.source_type}
- Description: {signal.content}"""

        def validate_queries(text: str) -> list[str]:
            data = json.loads(text)
            result = QueryGenerationResponse.model_validate(data)
            return [q[: MAX_QUERY_TOKENS * 4] for q in result.queries]  # rough char truncation

        queries = await call_llm_standalone(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            validate=validate_queries,
            temperature=0.7,
        )
        logger.info("    Queries: %s", queries)

        # Step 3: Embed each query
        query_embeddings = embedding_cache.embed_batch(queries)

        # Step 4: Cosine search per query
        query_results: list[list[SignalCandidate]] = []
        for q_emb in query_embeddings:
            candidates = store.search(q_emb, limit=10)
            query_results.append(candidates)

        # Step 5: LLM matching decision
        all_candidates: dict[str, SignalCandidate] = {}
        for candidates in query_results:
            for c in candidates:
                all_candidates[c.signal_id] = c

        if not all_candidates:
            report_id = str(uuid.uuid4())
            return GroupingDecision(
                report_id=report_id,
                is_new=True,
                title=signal.content[:75],
                reason="No candidates found in search",
            )

        matching_prompt = _build_matching_prompt(
            signal.content, signal.source_product, signal.source_type, queries, query_results
        )

        def validate_match(text: str) -> GroupingDecision:
            data = json.loads(text)
            match_type = data.get("match_type")
            if match_type == "existing":
                result = MatchFound.model_validate(data)
                matched = all_candidates.get(result.signal_id)
                if matched is None:
                    raise ValueError(f"signal_id {result.signal_id} not found in candidates")
                if result.query_index < 0 or result.query_index >= len(queries):
                    raise ValueError(f"query_index {result.query_index} out of range")
                return GroupingDecision(
                    report_id=matched.report_id,
                    is_new=False,
                    title=None,
                    reason=result.reason,
                )
            elif match_type == "new":
                new_group = NewGroup.model_validate(data)
                return GroupingDecision(
                    report_id=str(uuid.uuid4()),
                    is_new=True,
                    title=new_group.title,
                    reason=new_group.reason,
                )
            else:
                raise ValueError(f"Invalid match_type: {match_type}")

        return await call_llm_standalone(
            system_prompt=MATCHING_SYSTEM_PROMPT,
            user_prompt=matching_prompt,
            validate=validate_match,
            temperature=0.2,
        )
