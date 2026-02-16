import os
import json
from collections.abc import Callable
from typing import Literal, Optional, TypeVar

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
    SignalTypeExample,
)

logger = structlog.get_logger(__name__)

# TODO - any reason not to default to opus? Price seems kind of negligible right now?
MATCHING_MODEL = os.getenv("SIGNAL_MATCHING_LLM_MODEL", "claude-sonnet-4-5")
MAX_RETRIES = 3
MAX_RESPONSE_TOKENS = 4096
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
    for block in reversed(response.content):
        if block.type == "text":
            return block.text
    raise ValueError("No text content in response")


def _strip_markdown_json_fences(text: str) -> str:
    """Strip ```json ... ``` markdown fences that Claude sometimes wraps around JSON output."""
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        return stripped[len("```json") : -len("```")].strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped[len("```") : -len("```")].strip()
    return text


T = TypeVar("T")


async def call_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    validate: Callable[[str], T],
    thinking: bool = False,
    temperature: Optional[float] = 0.2,
    retries: int = MAX_RETRIES,
) -> T:
    client = get_async_anthropic_client()

    messages: list[MessageParam] = [
        {"role": "user", "content": user_prompt},
    ]

    # For non-thinking calls, pre-fill the assistant response with `{` to prevent markdown fences
    if not thinking:
        messages.append({"role": "assistant", "content": "{"})

    create_kwargs: dict = {
        "model": MATCHING_MODEL,
        "system": system_prompt,
        "messages": messages,
        "max_tokens": MAX_RESPONSE_TOKENS,
        "temperature": temperature,
    }

    # Later, we'll want to tune how many tokens we give over to thinking vs. producing output. Hard-coded for now.
    if thinking:
        create_kwargs["max_tokens"] = MAX_RESPONSE_TOKENS * 3
        create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": MAX_RESPONSE_TOKENS * 2}
        create_kwargs["temperature"] = 1  # Required for thinking

    last_exception: Exception | None = None
    for attempt in range(retries):
        response = None
        # NOTE - we explicitly don't want to retry if we fail to call the llm, or fail to extract text content,
        # only if we fail to validate the response.
        response = await client.messages.create(**create_kwargs)
        text_content = _extract_text_content(response)
        if thinking:
            text_content = _strip_markdown_json_fences(text_content)
        else:
            # Prepend the `{` we pre-filled
            text_content = "{" + text_content
        try:
            return validate(text_content)

        except Exception as e:
            logger.warning(
                f"LLM call failed (attempt {attempt + 1}/{retries}): {e}",
                attempt=attempt + 1,
                retries=retries,
            )
            if settings.DEBUG:
                logger.warning(
                    f"LLM response that failed validation:\n{text_content}",
                )
            if response:
                messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response failed validation. Error: {e}\n\nPlease try again with a valid JSON response.",
                }
            )
            last_exception = e
            continue

    raise last_exception or ValueError(f"LLM call failed after {retries} attempts")


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

        # Enforce max queries and truncate each to fit within embedding limits
        queries = result.queries[:MAX_QUERIES]
        return [_truncate_query_to_token_limit(q) for q in queries]

    return await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.7,
    )


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
