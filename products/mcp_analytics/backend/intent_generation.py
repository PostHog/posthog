"""On-demand session-intent summarisation.

Given an MCP session, fetch its per-tool-call ``$mcp_intent``s from ClickHouse
and condense them into a short natural-language summary via an LLM. Pure
generation only — caching and persistence live in ``logic.generate_session_intent``.
"""

from django.conf import settings

import openai
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable

MCP_TOOL_CALL_EVENT = "mcp_tool_call"
INTENT_MODEL = "gpt-4.1-mini"
MAX_INTENTS = 500
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
    AND properties.$mcp_session_id = {session_id}
    AND coalesce(properties.$mcp_intent, '') != ''
ORDER BY timestamp ASC
LIMIT {limit}
"""


def fetch_session_intents(team: Team, session_id: str) -> list[str]:
    """Return the session's recorded ``$mcp_intent``s in chronological order."""
    query = parse_select(
        _SESSION_INTENTS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
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
