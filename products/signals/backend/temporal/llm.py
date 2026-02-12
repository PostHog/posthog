import os
import json
from typing import Literal

from django.conf import settings

import tiktoken
import structlog
import posthoganalytics
from anthropic.types import MessageParam
from posthoganalytics.ai.anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    SignalCandidate,
    SignalData,
)

logger = structlog.get_logger(__name__)

MATCHING_MODEL = os.getenv("SIGNAL_MATCHING_LLM_MODEL", "claude-sonnet-4-5")
MAX_RETRIES = 3
MAX_QUERY_TOKENS = 2048
MAX_QUERIES = 3
TIMEOUT = 300.0


def get_async_anthropic_client() -> AsyncAnthropic:
    """Get configured AsyncAnthropic client with PostHog analytics."""
    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        raise ValueError("PostHog analytics client not configured")

    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    return AsyncAnthropic(
        api_key=api_key,
        posthog_client=posthog_client,
        timeout=TIMEOUT,
    )


# ============================================================================
# Query Generation
# ============================================================================


class QueryGenerationResponse(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)


QUERY_GENERATION_SYSTEM_PROMPT = f"""You are a signal grouping assistant. Your job is to generate search queries that will help find related signals in an embedding database.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
Related signals may be different types but connected by the same underlying cause, feature, or user journey. Note that "related" does not just mean "semantically similar", but "likely to share a common root cause or impact".

Given a new signal, generate 1-3 search queries that would help find related signals. Each query should be a natural language description that captures a different angle of what might be related:

1. The specific feature, page, or component involved
2. The type of user behavior or technical issue
3. The broader category or business impact

Keep queries concise but descriptive - they have a maximum length of {MAX_QUERY_TOKENS} tokens. Each query will be embedded and used for semantic similarity search.

Respond with a JSON object containing a "queries" array with 1-3 query strings. Return ONLY valid JSON, no other text."""


def _truncate_query_to_token_limit(query: str, max_tokens: int = MAX_QUERY_TOKENS) -> str:
    """Truncate a query string to fit within token limit for embedding."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(query)
        if len(tokens) <= max_tokens:
            return query
        truncated_tokens = tokens[:max_tokens]
        return enc.decode(truncated_tokens)
    except Exception as e:
        logger.warning(f"Failed to truncate with tiktoken, falling back to char limit: {e}")
        # Rough fallback: ~4 chars per token
        char_limit = max_tokens * 4
        return query[:char_limit]


def _extract_text_content(response) -> str:
    """Extract text content from Anthropic response."""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    raise ValueError("No text content in response")


async def generate_search_queries(
    description: str,
    source_product: str,
    source_type: str,
) -> list[str]:
    """
    Use LLM to generate 1-3 search queries for finding related signals.
    Returns queries truncated to fit within embedding token limits.
    """

    user_prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}"""

    client = get_async_anthropic_client()

    messages: list[MessageParam] = [
        {"role": "user", "content": user_prompt},
    ]

    last_exception = None
    for attempt in range(MAX_RETRIES):
        last_response_content: str | None = None
        try:
            response = await client.messages.create(
                model=MATCHING_MODEL,
                system=QUERY_GENERATION_SYSTEM_PROMPT,
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )

            last_response_content = _extract_text_content(response)

            data = json.loads(last_response_content)
            result = QueryGenerationResponse.model_validate(data)

            if len(result.queries) == 0:
                raise ValueError("LLM returned empty queries list")

            # Enforce max queries and truncate each to fit within embedding limits
            queries = result.queries[:MAX_QUERIES]
            truncated_queries = [_truncate_query_to_token_limit(q) for q in queries]

            logger.debug(
                f"Generated {len(truncated_queries)} search queries",
                source_product=source_product,
                source_type=source_type,
            )
            return truncated_queries

        except Exception as e:
            logger.warning(
                f"Failed to generate search queries (attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
            )
            if last_response_content:
                messages.append({"role": "assistant", "content": last_response_content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response failed validation. Error: {e}\n\nPlease try again with a valid JSON response.",
                }
            )
            last_exception = e
            continue

    if not last_exception:
        raise ValueError(f"Failed to generate search queries after {MAX_RETRIES} attempts")
    else:
        raise last_exception


# ============================================================================
# Signal Matching
# ============================================================================


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

    Args:
        description: The new signal's description
        source_product: Product that emitted the signal
        source_type: Type of signal
        queries: The search queries that were used
        query_results: Results from each query (parallel lists)

    Returns:
        ExistingReportMatch if a match is found, NewReportMatch otherwise
    """
    # Build hashmap for signal lookup
    candidates_by_id: dict[str, SignalCandidate] = {}
    for candidates in query_results:
        for c in candidates:
            candidates_by_id[c.signal_id] = c

    user_prompt = _build_matching_prompt(description, source_product, source_type, queries, query_results)
    client = get_async_anthropic_client()

    messages: list[MessageParam] = [
        {"role": "user", "content": user_prompt},
    ]

    last_exception = None
    for attempt in range(MAX_RETRIES):
        last_response_content: str | None = None
        try:
            response = await client.messages.create(
                model=MATCHING_MODEL,
                system=MATCHING_SYSTEM_PROMPT,
                messages=messages,
                max_tokens=1024,
                temperature=0.2,
            )

            last_response_content = _extract_text_content(response)

            data = json.loads(last_response_content)
            result = _parse_match_response(data)

            if isinstance(result, LLMMatchFound):
                matched = candidates_by_id.get(result.signal_id)
                if matched is None:
                    raise ValueError(f"signal_id {result.signal_id} not found in candidates")

                logger.debug(
                    "Signal matched to existing report",
                    report_id=matched.report_id,
                    signal_id=result.signal_id,
                )
                return ExistingReportMatch(report_id=matched.report_id)

            logger.debug(
                "Signal creating new report",
                title=result.title,
            )
            return NewReportMatch(title=result.title, summary=result.summary)

        except Exception as e:
            logger.warning(
                f"Failed to match signal (attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
            )
            if last_response_content:
                messages.append({"role": "assistant", "content": last_response_content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response failed validation. Error: {e}\n\nPlease try again with a valid JSON response.",
                }
            )
            last_exception = e
            continue

    if not last_exception:
        raise ValueError(f"Failed to get valid LLM response after {MAX_RETRIES} attempts")
    else:
        raise last_exception


# ============================================================================
# Signal Summarization
# ============================================================================


class SummarizeSignalsResponse(BaseModel):
    title: str = Field(description="A short, descriptive title for the report (max 100 chars)")
    summary: str = Field(description="A 2-4 sentence summary of the key findings")


SUMMARIZE_SYSTEM_PROMPT = """You are a product analytics assistant. Your job is to summarize a collection of related signals into a concise report.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
They have been grouped together because they share a common underlying cause.

Given a list of signals, produce:
1. A short, descriptive title (max 100 characters) that captures the essence of what these signals are about
2. A 2-4 sentence summary that explains:
   - What the signals indicate
   - The potential impact or significance
   - Any patterns or trends observed

Signals have a weight - this is a number, between 0 and 1, representing how important the signal is. Signals with higher weights are more important.

Signal groups have a weight equal to the sum of all their signals' weights, and when the group has a weight of 1, you're asked to produce a report about them.

Be specific and actionable. Avoid generic phrases like "various issues detected".

Respond with a JSON object containing "title" and "summary" fields. Return ONLY valid JSON, no other text."""


def _build_summarize_prompt(signals: list[SignalData]) -> str:
    prompt = "SIGNALS TO SUMMARIZE:\n\n"

    for i, signal in enumerate(signals):
        prompt += f"""Signal {i + 1}:
- Source: {signal.source_product} / {signal.source_type}
- Weight: {signal.weight}
- Timestamp: {signal.timestamp}
- Description: {signal.content}
"""
        if signal.extra:
            prompt += f"- Extra metadata: {signal.extra}\n"
        prompt += "\n"

    return prompt


async def summarize_signals(signals: list[SignalData]) -> tuple[str, str]:
    """
    Summarize a list of signals into a title and summary.

    Args:
        signals: List of SignalData objects

    Returns:
        Tuple of (title, summary)
    """
    user_prompt = _build_summarize_prompt(signals)
    client = get_async_anthropic_client()

    messages: list[MessageParam] = [
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(MAX_RETRIES):
        last_response_content: str | None = None
        try:
            response = await client.messages.create(
                model=MATCHING_MODEL,
                system=SUMMARIZE_SYSTEM_PROMPT,
                messages=messages,
                max_tokens=1024,
                temperature=0.3,
            )

            last_response_content = _extract_text_content(response)

            data = json.loads(last_response_content)
            result = SummarizeSignalsResponse.model_validate(data)

            if len(result.title) > 100:
                raise ValueError("Title exceeds maximum length")

            logger.debug(
                "Summarized signals",
                signal_count=len(signals),
                title=result.title,
            )
            return result.title, result.summary

        except Exception as e:
            logger.warning(
                f"Failed to summarize signals (attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
            )
            if last_response_content:
                messages.append({"role": "assistant", "content": last_response_content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response failed validation. Error: {e}\n\nPlease try again with a valid JSON response.",
                }
            )
            continue

    raise ValueError(f"Failed to summarize signals after {MAX_RETRIES} attempts")
