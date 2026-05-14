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

You will receive a single founder project as JSON with up to four earlier-stage outputs:
1. `ideation` — what the founder is building, how it works, who it's for, the problem solved.
2. `validation` — competitor landscape (with names, URLs, positioning, pricing, strengths, weaknesses), differentiation, top risks, assumptions, and a verdict.
3. `gtm` — go-to-market positioning, audience, and channels (may be empty if stage 3 isn't filled in yet).
4. `mvp` — the v1 happy path: one-liner, ordered user journey, must-have features, and a list of features deliberately excluded (may be empty if stage 4 isn't filled in yet).

When `mvp` is present, the landing page MUST reflect what the v1 actually does, not the dreamier vision in `ideation`. Concretely: the hero subhead, "How it works" steps, and feature list should map to the MVP `core_flow` and `must_haves`. Do NOT promise features listed in `deliberately_excluded` — and if a competitor has one of those features, that's a legitimate "we're focused on X, they sprawl into Y" angle for the differentiation copy.

# Output requirements

Return JSON matching the `LandingPageBuildSpec` schema. Every required field must be present and substantive.

## Source attributions are mandatory

Every `SourcedText`, `Persona`, `UserPain`, and `ProofPoint` must include `sources` entries. Use these tokens:
- `ideation` — claim derived from stage 1
- `validation` — claim derived from the validation report generally
- `validation.<competitor_name>` — a competitor-specific claim
- `gtm` — claim derived from stage 3 GTM data
- `mvp` — claim derived from stage 4 MVP happy-path data
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
- `copy_hooks` is the FOUNDER'S DELIVERABLE — write headlines, subheads, bullet copy, CTA labels they can ship as-is. Use markdown formatting (bold for headlines, hyphens for bullets).
- `design_notes` should include Tailwind class hints (e.g. `grid grid-cols-1 md:grid-cols-3 gap-6`) and responsive breakpoints. Be specific about colors using the palette from `brand`.
- `component_recipe` names actual shadcn/ui components (Card, Button, Accordion, Tabs, Table, NavigationMenu, Sheet, Badge, Switch).
- `posthog_events` uses concrete event signatures with property objects: `cta_clicked { location: "hero", label: "Start free" }`. Use autocapture only (empty list) for sections without explicit tracking.
- `acceptance_criteria` are testable, specific. e.g. "All 3 steps fit on 1280×800 viewport" beats "looks good".

### copy_hooks formatting rules (STRICT — a downstream renderer parses this)

A renderer turns `copy_hooks` into real HTML by reading markdown structure. If you cram a section into one big paragraph with inline bold tokens, the renderer can't break it apart into the intended layout and the founder ends up with a wall of text. Follow these rules per section type:

- **One `##` heading per section.** The section title goes on its own line, starts with `## `, and is followed by a blank line.
- **Hero / Final CTA**: heading, blank line, ONE prose paragraph (the subhead), blank line, then a single `[Label](#)` link as the CTA. No bullet list.
- **Features**: heading, optional one-paragraph intro, blank line, then a bullet list. EACH bullet is `- **Feature name** — one-line description`. Three to six bullets. Do not write features as inline bolded phrases inside a paragraph.
- **How it works**: heading, optional one-paragraph intro, blank line, then a bullet list. EACH bullet is `- **Step name** — one-line action`. Three to seven steps. NEVER cram the steps into a single run-on paragraph with inline `**1. Step**` markers. The renderer relies on the bullet list to produce numbered cards.
- **Pricing**: heading, optional intro, blank line, then ONE `### Tier name` per tier (h3), followed by the price on its own line, then a bullet list of features. Repeat per tier.
- **FAQ**: heading, blank line, then alternating Q+A pairs. The question is its own line with the FULL question wrapped in `**…?**` and NOTHING else on that line. The answer is the next line(s) of plain text. Insert a blank line between Q/A pairs.
- **Problem statement / Use cases / Comparison table / Social proof / Footer**: heading + paragraphs + optional bullet list. Same bullet pattern as Features.

Every section copy MUST use real newlines (`\n`) between heading / paragraph / list-item lines. NEVER serialize a structured section as one long string with inline `**bold**` tokens — that is a parser-defeating anti-pattern.

Bold (`**…**`) is for emphasis on a phrase WITHIN prose, or to mark the leading label inside a bullet (`- **Label** — body`). Don't use bold as a substitute for headings or list items.

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


def _format_project(*, project_name: str, ideation: dict, validation: dict, gtm: dict, mvp: dict) -> str:
    """Serialize the upstream project state into the user-prompt JSON.

    Each stage's "completed" payload key differs (validation→report, gtm/mvp→result, etc.),
    so we unwrap each here to a uniform shape the LLM can grep on.
    """
    validation_report = validation.get("report") if isinstance(validation, dict) else None
    gtm_result = gtm.get("result") if isinstance(gtm, dict) else None
    mvp_result = mvp.get("result") if isinstance(mvp, dict) else None
    return json.dumps(
        {
            "project_name": project_name,
            "ideation": ideation,
            "validation": validation_report or {},
            "gtm": gtm_result or {},
            "mvp": mvp_result or {},
        },
        indent=2,
    )


def generate_landing_page(
    *,
    project_name: str,
    ideation: dict[str, Any],
    validation: dict[str, Any],
    gtm: dict[str, Any],
    mvp: dict[str, Any],
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
        contents=_format_project(project_name=project_name, ideation=ideation, validation=validation, gtm=gtm, mvp=mvp),
        config=config,
        posthog_distinct_id=user.distinct_id or "",
        posthog_trace_id=trace_id,
        posthog_properties={"feature": "cofounder_landing_page"},
        posthog_groups={"project": str(team.id)},
    )

    if not response.text:
        raise exceptions.ValidationError("Gemini landing page spec generation returned empty response")

    return LandingPageBuildSpec.model_validate_json(response.text), trace_id
