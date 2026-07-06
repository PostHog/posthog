"""On-demand session-intent summarisation.

Given an MCP session, fetch its per-tool-call ``$mcp_intent``s from ClickHouse
and condense them into a short natural-language summary via an LLM. Pure
generation only — caching and persistence live in ``logic.generate_session_intent``.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

import openai
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable

INTENT_MODEL = "gpt-4.1-mini"
MAX_INTENTS = 500
# Fallback scan bound for the session-detail queries (tool calls + intents) — a single $session_id
# isn't in the events sort key, so without a timestamp bound the scan covers the team's full
# history. Callers normally pass the session's start; this covers ones that don't.
SESSION_EVENTS_LOOKBACK = timedelta(days=7)
# Persisted (and returned) when a session has no recorded intents, so callers
# get a definitive answer and we don't re-query ClickHouse on the next request.
NO_INTENT_MESSAGE = "No agent intent was recorded for this session."

SYSTEM_PROMPT = (
    "You are given the per-tool-call intents an AI agent recorded during one MCP session, in "
    "chronological order. Summarise the agent's overall goal in at most two sentences — aim for "
    "under 20 words total. "
    "State the goal directly; do NOT start with 'The agent', 'The user', 'This session', or similar. "
    "Be concrete: name the actual product, metric, person, or workflow involved — never generic "
    "phrases like 'analytics question' or 'data exploration'. "
    "If the intents span unrelated tasks, describe only the dominant one. "
    "Do not list tools, echo the input, or add filler. "
    "Example: 'Investigating why signup funnel conversion dropped last week.'"
)

_SESSION_INTENTS_SQL = """
SELECT toString(properties.$mcp_intent) AS intent
FROM events
WHERE event = {event}
    AND timestamp >= {date_from}
    AND $session_id = {session_id}
    AND coalesce(properties.$mcp_intent, '') != ''
ORDER BY timestamp ASC
LIMIT {limit}
"""


def fetch_session_intents(team: Team, session_id: str, date_from: datetime | None = None) -> list[str]:
    """Return the session's recorded ``$mcp_intent``s in chronological order.

    ``date_from`` is the timestamp lower bound that lets the events sort key prune the scan,
    mirroring ``logic.list_mcp_tool_calls``: callers pass the session's start so the whole session
    resolves, and it falls back to ``SESSION_EVENTS_LOOKBACK`` for callers that don't.
    """
    query = parse_select(
        _SESSION_INTENTS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "date_from": ast.Constant(value=date_from or (timezone.now() - SESSION_EVENTS_LOOKBACK)),
            "session_id": ast.Constant(value=session_id),
            "limit": ast.Constant(value=MAX_INTENTS),
        },
    )
    with tags_context(
        product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name="mcp_analytics_session_intent"
    ):
        response = execute_hogql_query(query=query, team=team)
    return [str(row[0]) for row in (response.results or []) if row[0]]


def _build_user_prompt(intents: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {intent}" for i, intent in enumerate(intents))
    return f"Per-tool-call intents (chronological):\n{numbered}\n\nSummarise the agent's overall goal in at most two short, concrete sentences."


def summarize_intents(intents: list[str], team: Team) -> str:
    """Condense the intents via the LLM. Blocking — the endpoint runs it inline.

    Raises ``IntentGenerationUnavailable`` when the LLM is unconfigured or the request fails,
    so the endpoint can answer with a clean 503 rather than a 500.
    """
    if not settings.OPENAI_API_KEY:
        raise IntentGenerationUnavailable("OPENAI_API_KEY is not configured")

    client = OpenAI(posthog_client=posthoganalytics.default_client, base_url=settings.OPENAI_BASE_URL)
    try:
        response = client.chat.completions.create(  # type: ignore
            model=INTENT_MODEL,
            temperature=0,
            max_tokens=90,
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(intents)},
            ],
            user=f"team/{team.id}/mcp-analytics-session-intent",
            posthog_properties={"ai_product": "mcp_analytics", "ai_feature": "session-intent-generation"},
        )
    except openai.OpenAIError as e:
        raise IntentGenerationUnavailable("LLM request failed") from e
    content = response.choices[0].message.content if response.choices else None
    summary = (content or "").strip()
    if not summary:
        raise IntentGenerationUnavailable("LLM returned an empty summary")
    return summary


# Project-level activity digest: what agents are trying to do across the whole
# server, for the dashboard's low-volume activity stage.
MAX_DIGEST_INTENTS = 100
# Bounds the intent scan so the events sort key can prune it. Generous because
# activity-stage servers are low-volume and their history is short by definition.
DIGEST_LOOKBACK = timedelta(days=90)

DIGEST_SYSTEM_PROMPT = (
    "You are given the per-tool-call intents AI agents recorded while using one MCP server, "
    "most recent first. Summarise what agents are trying to do with this server in at most "
    "three short sentences. Group similar intents into themes and lead with the most common one. "
    "Be concrete: name the actual workflows, products, or entities involved — never generic "
    "phrases like 'various tasks' or 'data exploration'. Do not list tools, echo the input, or add filler."
)

_PROJECT_INTENTS_SQL = """
SELECT toString(properties.$mcp_intent) AS intent
FROM events
WHERE event = {event}
    AND timestamp >= {date_from}
    AND coalesce(properties.$mcp_intent, '') != ''
ORDER BY timestamp DESC
LIMIT {limit}
"""


def fetch_recent_project_intents(team: Team) -> list[str]:
    """Return the project's most recent ``$mcp_intent``s across all sessions, newest first."""
    query = parse_select(
        _PROJECT_INTENTS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "date_from": ast.Constant(value=timezone.now() - DIGEST_LOOKBACK),
            "limit": ast.Constant(value=MAX_DIGEST_INTENTS),
        },
    )
    with tags_context(
        product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name="mcp_analytics_intent_digest"
    ):
        response = execute_hogql_query(query=query, team=team)
    return [str(row[0]) for row in (response.results or []) if row[0]]


def _build_digest_prompt(intents: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {intent}" for i, intent in enumerate(intents))
    return (
        f"Per-tool-call intents (most recent first):\n{numbered}\n\n"
        "Summarise what agents are trying to do with this server, in at most three short sentences."
    )


def summarize_project_intents(intents: list[str], team: Team) -> str:
    """Condense the project's intents into an activity digest. Blocking — the endpoint runs it inline.

    Raises ``IntentGenerationUnavailable`` when the LLM is unconfigured or the request fails,
    so the endpoint can answer with a clean 503 rather than a 500.
    """
    if not settings.OPENAI_API_KEY:
        raise IntentGenerationUnavailable("OPENAI_API_KEY is not configured")

    client = OpenAI(posthog_client=posthoganalytics.default_client, base_url=settings.OPENAI_BASE_URL)
    try:
        response = client.chat.completions.create(  # type: ignore
            model=INTENT_MODEL,
            temperature=0,
            max_tokens=140,
            timeout=30,
            messages=[
                {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
                {"role": "user", "content": _build_digest_prompt(intents)},
            ],
            user=f"team/{team.id}/mcp-analytics-intent-digest",
            posthog_properties={"ai_product": "mcp_analytics", "ai_feature": "activity-intent-digest"},
        )
    except openai.OpenAIError as e:
        raise IntentGenerationUnavailable("LLM request failed") from e
    content = response.choices[0].message.content if response.choices else None
    digest = (content or "").strip()
    if not digest:
        raise IntentGenerationUnavailable("LLM returned an empty digest")
    return digest
