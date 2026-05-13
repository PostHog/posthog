"""ValidationService for the cofounder product.

Two-pass design:
  1. Grounded research call — Gemini with `google_search` tool fetches real competitor
     information from the web. Output: plain text + citations.
  2. Structured synthesis call — Gemini with strict JSON schema produces the final
     ValidationReport, using the research text as context.

Why two passes: Gemini's strict JSON mode (`response_mime_type=application/json` +
`response_json_schema`) historically does not combine reliably with tools (search grounding).
Splitting also gives sharper prompts and keeps the final-report call deterministic.

Mirror the pattern from products/surveys/backend/llm/client.py and
products/product_tours/backend/llm/client.py — `posthoganalytics.ai.gemini` is the
PostHog-wrapped Gemini client that handles billing, tracing, and team grouping.
"""

import uuid
from collections.abc import Callable
from typing import Any

from django.conf import settings

import structlog
import posthoganalytics
from google.genai.types import GenerateContentConfig, GoogleSearch, Tool
from posthoganalytics.ai.gemini import genai
from rest_framework import exceptions

from posthog.models.team.team import Team
from posthog.models.user import User

from .schemas import IdeationInput, ValidationReport

logger = structlog.get_logger(__name__)

# Gemini 2.5 Flash hits the sweet spot for this task: fast, cheap, strong JSON + grounding
# support. Bump to gemini-2.5-pro if verdict quality matters more than cost.
RESEARCH_MODEL = "gemini-2.5-flash"
SYNTHESIS_MODEL = "gemini-2.5-flash"

RESEARCH_SYSTEM_PROMPT = """You are a market research analyst helping a founder understand the competitive landscape for a new startup idea.

Given a description of the founder's idea (what they want to build, how it works, who it's for, and the problem it solves), use search to identify 3-6 real, current companies that compete directly or indirectly.

For each competitor, capture in plain prose:
- Company name (real names only — no invented categories)
- One sentence on what they do
- How they go to market (pricing model, distribution channel, target segment)
- Approximate pricing if publicly known
- Two or three concrete strengths
- Two or three concrete weaknesses
- A primary source URL (homepage, pricing page, or recent press article) — REQUIRED for every competitor. Write it on its own line as `Source: <URL>` after the bullets.

Be specific and current. If you cannot find genuine competitors after searching, say so honestly. Do not invent companies and do not invent URLs — every URL must come from your search results.

Return your findings as plain text with company names as headers. Do not return JSON — a separate downstream step will structure this."""

SYNTHESIS_SYSTEM_PROMPT = """You are a seasoned startup operator helping a founder critically validate their idea before they commit significant time and money. You have seen many startups fail from preventable mistakes. The founder benefits more from a hard truth than from validation theater.

You will receive:
1. The founder's idea (what / how / who / problem).
2. Research findings on the competitive landscape, gathered separately.

Produce a structured validation report covering:
- Competitors — use the research findings; reflect real companies, not categories. For each competitor's `source_url`, copy the `Source:` URL from the research findings verbatim — do not invent or modify URLs. If no URL was provided for a competitor in the findings, set `source_url` to null.
- Differentiation — where this idea sits in the landscape, what (if anything) is defensible, what specific gap it fills.
- Three to five critical assumptions, ordered by riskiness (riskiest first). Each must be a single testable claim that, if false, would meaningfully threaten the idea.
- One concrete validation experiment per assumption — cheap, fast, runnable this week. Reference the assumption by its zero-indexed position.
- Three to six top risks across market, technical, regulatory, execution, timing, and other categories. Name specific failure modes, not generic concerns.
- A verdict — 1-10 score, confidence level, one short honest paragraph of reasoning, and 3-5 prioritized next steps.

Be critical and specific. If the idea has fatal flaws, say so plainly. If it has clear strengths, say that too. Avoid hedging language that adds no information."""


def create_gemini_client() -> Any:
    """Return a PostHog-wrapped Gemini client. Pattern lifted from surveys/product_tours."""
    if settings.DEBUG and posthoganalytics.disabled:
        posthoganalytics.disabled = False
        if not posthoganalytics.host:
            posthoganalytics.host = settings.SITE_URL

    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        logger.warning("PostHog default_client not available, LLM analytics will not be tracked")

    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
        posthog_client=posthog_client,
    )


def _format_ideation(ideation: IdeationInput) -> str:
    return (
        f"What they want to build: {ideation.what}\n"
        f"How it works: {ideation.how}\n"
        f"Who it's for: {ideation.who}\n"
        f"Problem it solves: {ideation.problem}"
    )


def _research_competitors(
    *,
    ideation: IdeationInput,
    team: Team,
    user: User,
    trace_id: str,
) -> str:
    """Pass 1: grounded research call. Returns raw text findings with inline citations."""
    client = create_gemini_client()

    config = GenerateContentConfig(
        system_instruction=RESEARCH_SYSTEM_PROMPT,
        tools=[Tool(google_search=GoogleSearch())],
        temperature=0.2,
    )

    response = client.models.generate_content(
        model=RESEARCH_MODEL,
        contents=_format_ideation(ideation),
        config=config,
        posthog_distinct_id=user.distinct_id or "",
        posthog_trace_id=trace_id,
        posthog_properties={"feature": "cofounder_validation", "pass": "research"},
        posthog_groups={"project": str(team.id)},
    )

    if not response.text:
        raise exceptions.ValidationError("Gemini research pass returned empty response")

    return response.text


def _synthesize_report(
    *,
    ideation: IdeationInput,
    research_text: str,
    team: Team,
    user: User,
    trace_id: str,
) -> ValidationReport:
    """Pass 2: structured synthesis. Returns a typed ValidationReport instance."""
    client = create_gemini_client()

    config = GenerateContentConfig(
        system_instruction=SYNTHESIS_SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=ValidationReport.model_json_schema(),
        temperature=0.3,
    )

    user_prompt = f"Founder's idea:\n{_format_ideation(ideation)}\n\nCompetitor research findings:\n{research_text}"

    response = client.models.generate_content(
        model=SYNTHESIS_MODEL,
        contents=user_prompt,
        config=config,
        posthog_distinct_id=user.distinct_id or "",
        posthog_trace_id=trace_id,
        posthog_properties={"feature": "cofounder_validation", "pass": "synthesis"},
        posthog_groups={"project": str(team.id)},
    )

    if not response.text:
        raise exceptions.ValidationError("Gemini synthesis pass returned empty response")

    return ValidationReport.model_validate_json(response.text)


def run_validation(
    *,
    ideation_payload: dict[str, Any],
    team: Team,
    user: User,
    on_pass_change: Callable[[str], None] | None = None,
) -> tuple[ValidationReport, str]:
    """Run the full two-pass validation flow. Returns the report and the shared trace_id.

    `on_pass_change(pass_name)` is invoked just before each pass starts ("research", "synthesis").
    Used by the Celery task to write `validation.current_pass` so the frontend can render
    accurate staged progress instead of guessing from elapsed time.

    Raises pydantic.ValidationError if `ideation_payload` does not match IdeationInput,
    and propagates any Gemini API errors. The Celery task wrapper is responsible for
    catching and writing failure state to ValidationReport.error.
    """
    ideation = IdeationInput.model_validate(ideation_payload)
    trace_id = str(uuid.uuid4())

    if on_pass_change:
        on_pass_change("research")
    research_text = _research_competitors(ideation=ideation, team=team, user=user, trace_id=trace_id)

    if on_pass_change:
        on_pass_change("synthesis")
    report = _synthesize_report(ideation=ideation, research_text=research_text, team=team, user=user, trace_id=trace_id)
    return report, trace_id
