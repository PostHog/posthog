"""Stage-3 conceptual GTM generator.

Single Gemini call (no grounded research — validation already covered the landscape). Reads
ideation + validation report and produces a strategic positioning brief: target segments,
pricing philosophy, channels. NOT the practical launch playbook (that's `practical_steps/`).
"""

import json
import uuid
from typing import Any

from django.conf import settings

import structlog
import posthoganalytics
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from rest_framework import exceptions

from posthog.models.team.team import Team
from posthog.models.user import User

from .schemas import GTMSummary

logger = structlog.get_logger(__name__)

GTM_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are a startup positioning strategist helping a founder turn a validated idea into a tight go-to-market thesis.

You will receive:
1. `ideation` — what the founder is building (what, how, who, problem).
2. `validation` — the competitor landscape, differentiation, top risks, assumptions, verdict.

Produce a CONCEPTUAL GTM summary. This is positioning, pricing philosophy, and channel strategy — NOT a launch playbook. A separate downstream step writes the actual posts/copy.

# Output requirements

Return JSON matching the `GTMSummary` schema. Every required field must be present and substantive.

## Positioning statement

One paragraph. Reads like a founder describing the company at a dinner party — not marketing copy. Specifies who it's for, what category it plays in, and the one sentence that explains why it wins.

## Target segments

- `primary_segment` is the WEDGE — the single audience the founder should chase first. Pick the segment with the strongest pull from the validation report. Be specific: "Solo SaaS founders, 200-3k Twitter followers, pre-launch" beats "early-stage founders".
- `secondary_segments`: 1-3 adjacent audiences to expand into AFTER the wedge is proven. Each should be reachable through a different channel or motion than the primary.
- For each segment, `why_reachable_now` must be time-anchored and concrete (e.g. "These founders are actively shipping during the YC W26 cohort window" beats "They have growing interest").

## Category

State plainly: new-category play, wedge inside an existing category, or commodified-category replay. The validation report names competitors — use that to decide.

## Moat

Concrete and named. "Compounding data flywheel from real usage" beats "network effects". "Three-month switching cost from custom integrations" beats "high switching costs". If there isn't a real moat, say "no defensible moat at the product layer — this competes on execution speed and distribution".

## Pricing

- `pricing_philosophy`: per-seat vs usage vs flat vs freemium, and WHY this shape fits the segment + value delivered. One paragraph.
- `pricing_tiers`: 2-4 tiers, ordered low to high. Concrete price points (in $). Each tier references a `target_segment` by name. `value` describes what the buyer gets in plain language, not marketing bullets.

## Channels

- `primary_channel`: one of "community", "content", "paid", "partnerships", "sales-led", "PLG/viral". Pick ONE — the highest-leverage channel for the primary segment.
- `secondary_channels`: 2-4 in priority order. Same vocabulary.

# Voice

Be opinionated. The founder benefits from a strong recommendation they can push back on. Avoid hedging ("it depends", "you might consider", "various options"). Avoid marketing words ("revolutionary", "leverage", "unlock value", "10x"). Avoid surveys-speak ("ICP", "TAM/SAM/SOM"). Write like a seasoned operator talking to a peer."""


def _create_client() -> Any:
    """PostHog-wrapped Gemini client — mirrors validation/service.py."""
    if settings.DEBUG and posthoganalytics.disabled:
        posthoganalytics.disabled = False
        if not posthoganalytics.host:
            posthoganalytics.host = settings.SITE_URL

    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        logger.warning("PostHog default_client not available, LLM analytics will not be tracked")

    return genai.Client(api_key=settings.GEMINI_API_KEY, posthog_client=posthog_client)


def _format_payload(*, ideation: dict[str, Any], validation: dict[str, Any]) -> str:
    """Serialize upstream state as JSON for the model."""
    validation_report = validation.get("report") if isinstance(validation, dict) else None
    return json.dumps(
        {
            "ideation": ideation,
            "validation": validation_report or {},
        },
        indent=2,
    )


def generate_gtm_summary(
    *,
    ideation: dict[str, Any],
    validation: dict[str, Any],
    team: Team,
    user: User,
) -> tuple[GTMSummary, str]:
    """Run the synthesis pass. Returns (summary, trace_id). Caller owns persistence."""
    client = _create_client()
    trace_id = str(uuid.uuid4())

    config = GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=GTMSummary.model_json_schema(),
        temperature=0.4,
    )

    response = client.models.generate_content(
        model=GTM_MODEL,
        contents=_format_payload(ideation=ideation, validation=validation),
        config=config,
        posthog_distinct_id=user.distinct_id or "",
        posthog_trace_id=trace_id,
        posthog_properties={"feature": "cofounder_gtm_summary"},
        posthog_groups={"project": str(team.id)},
    )

    if not response.text:
        raise exceptions.ValidationError("Gemini GTM summary generation returned empty response")

    return GTMSummary.model_validate_json(response.text), trace_id
