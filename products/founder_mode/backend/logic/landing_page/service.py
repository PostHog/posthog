"""Stage-4 build-spec generator.

Single Gemini call (no grounded research — validation already did that for us). The model
consumes the FounderProject's ideation + validation + gtm and emits a `LandingPageBuildSpec`
that an engineer or AI coding agent can take and build in Next.js + Tailwind + shadcn/ui.

The output is intentionally a *spec*, not a rendered page — the founder uses it as a brief.
Per-section copy/design/event/AC quality is the priority over visual fidelity here.
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

from .schemas import LandingPageBuildSpec

logger = structlog.get_logger(__name__)

LANDING_PAGE_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are an experienced product marketer + technical PM writing a *build specification* for a founder's first landing page. The deliverable is NOT a rendered page — it's a detailed brief that a developer (or an AI coding agent like Claude Code / Cursor) will take and turn into a real Next.js + Tailwind + shadcn/ui repo.

You will receive a single founder project as JSON with three earlier-stage outputs:
1. `ideation` — what the founder is building, how it works, who it's for, the problem solved.
2. `validation` — competitor landscape (with names, URLs, positioning, pricing, strengths, weaknesses), differentiation, top risks, assumptions, and a verdict.
3. `gtm` — go-to-market positioning, audience, and channels (may be empty if stage 3 isn't filled in yet).

# Output requirements

Return JSON matching the `LandingPageBuildSpec` schema. Every required field must be present and substantive.

## Source attributions are mandatory

Every `SourcedText`, `Persona`, `UserPain`, and `ProofPoint` must include `sources` entries. Use these tokens:
- `ideation` — claim derived from stage 1
- `validation` — claim derived from the validation report generally
- `validation.<competitor_name>` — a competitor-specific claim
- `gtm` — claim derived from stage 3 GTM data
- `brand notebook` — if brand data exists in the project; otherwise mark `brand.source = "synthesized"` instead
- `synthesized from <X + Y>` — for derived value props that combine multiple sources

NEVER invent a source. If a claim isn't supported by the input, don't make the claim.

## Competitor profiles

For EVERY competitor in `validation.report.competitors` that has a non-null `source_url`, emit a `CompetitorPositioning` entry. Copy the `source_url` into `url` VERBATIM. Reasonable defaults:
- `pages_fetched`: ["/", "/pricing"] if the competitor likely has a pricing page; ["/"] otherwise
- `positioning`: derived from the competitor's `description` + `positioning` fields in validation
- `pricing`: take from the competitor's `pricing` field; if null, write "Not publicly disclosed"
- `voice_notes`: infer from the competitor's strengths/weaknesses — 'friendly', 'enterprise-leaning', 'developer-y', etc.

If a competitor has no `source_url`, add a `CoverageGap` entry with reason "No source URL captured during validation pass."

## Page sections

Always emit these core sections in this order, with `classification: "core"`:
1. Nav bar
2. Hero
3. Social proof
4. Features
5. How it works
6. Pricing
7. FAQ
8. Final CTA
9. Footer

Insert these OPTIONAL sections (`classification: "optional_included"`, with `why_included` populated) only when justified by the inputs:
- **Problem statement** — when validation surfaces strong evidence of a specific pain (interviews, polls, quantitative signal). Cite that evidence in `why_included`.
- **Use cases** — when the project has two or more distinct ICP personas. Cite which personas.
- **Comparison table** — when validation contains TWO OR MORE real competitors with non-null `source_url`. Cite the competitors.

For each optional section you skip, add an entry to `skipped_sections` with a one-sentence reason that cites the missing upstream input (e.g. "Validation only surfaced one competitor with a usable URL — comparison table needs at least two").

## Section quality

For each `PageSection`:
- `copy_hooks` is the FOUNDER'S DELIVERABLE — write headlines, subheads, bullet copy, CTA labels they can ship as-is. Use markdown formatting (bold for headlines, hyphens for bullets). For sections like FAQ, write actual question-and-answer pairs, not placeholders.
- `design_notes` should include Tailwind class hints (e.g. `grid grid-cols-1 md:grid-cols-3 gap-6`) and responsive breakpoints. Be specific about colors using the palette from `brand`.
- `component_recipe` names actual shadcn/ui components (Card, Button, Accordion, Tabs, Table, NavigationMenu, Sheet, Badge, Switch).
- `posthog_events` uses concrete event signatures with property objects: `cta_clicked { location: "hero", label: "Start free" }`. Use autocapture only (empty list) for sections without explicit tracking.
- `acceptance_criteria` are testable, specific. e.g. "All 3 steps fit on 1280×800 viewport" beats "looks good".

## Brand

Pick `brand.source = "notebook"` only if the project has unambiguous brand inputs. If the brand has to be inferred from ideation/validation/gtm, use `"synthesized"`. If key brand decisions (palette, tone) are genuinely ambiguous, use `"user_questions"` — but only as a last resort.

The palette MUST include concrete hex codes. The typography MUST include real font names. References MUST be real sites (Resend, Linear, Cal.com, Stripe, Vercel, etc.).

## What to avoid

- Generic marketing copy ("revolutionary", "leverage", "unlock value", "10x your X")
- Fabricated testimonials, fake company logos, "As featured in" press placeholders
- Vague design notes ("clean layout", "modern look") — be specific
- FAQs that don't address validation risks — every FAQ must address a skeptical visitor objection grounded in the validation report
- Inventing competitor URLs not present in the validation report

Be opinionated and concrete. The founder will read this and either ship it or hand it to an AI coding agent — write copy and specs they can actually use."""


def _create_client() -> Any:
    """PostHog-wrapped Gemini client — same pattern as validation/service.py."""
    if settings.DEBUG and posthoganalytics.disabled:
        posthoganalytics.disabled = False
        if not posthoganalytics.host:
            posthoganalytics.host = settings.SITE_URL

    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        logger.warning("PostHog default_client not available, LLM analytics will not be tracked")

    return genai.Client(api_key=settings.GEMINI_API_KEY, posthog_client=posthog_client)


def _format_project(*, project_name: str, ideation: dict, validation: dict, gtm: dict) -> str:
    """Serialize the upstream project state into the user-prompt JSON."""
    validation_report = validation.get("report") if isinstance(validation, dict) else None
    return json.dumps(
        {
            "project_name": project_name,
            "ideation": ideation,
            "validation": validation_report or {},
            "gtm": gtm,
        },
        indent=2,
    )


def generate_landing_page(
    *,
    project_name: str,
    ideation: dict[str, Any],
    validation: dict[str, Any],
    gtm: dict[str, Any],
    team: Team,
    user: User,
) -> tuple[LandingPageBuildSpec, str]:
    """Run the synthesis pass. Returns (spec, trace_id). Caller owns persistence."""
    client = _create_client()
    trace_id = str(uuid.uuid4())

    config = GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=LandingPageBuildSpec.model_json_schema(),
        # Lower than copy-only generation because the spec has many factual fields (sources,
        # competitor data, event names) where we want consistency, not creativity.
        temperature=0.4,
    )

    response = client.models.generate_content(
        model=LANDING_PAGE_MODEL,
        contents=_format_project(project_name=project_name, ideation=ideation, validation=validation, gtm=gtm),
        config=config,
        posthog_distinct_id=user.distinct_id or "",
        posthog_trace_id=trace_id,
        posthog_properties={"feature": "cofounder_landing_page"},
        posthog_groups={"project": str(team.id)},
    )

    if not response.text:
        raise exceptions.ValidationError("Gemini landing page spec generation returned empty response")

    return LandingPageBuildSpec.model_validate_json(response.text), trace_id
