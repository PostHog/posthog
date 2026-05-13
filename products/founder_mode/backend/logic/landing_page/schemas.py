"""Pydantic schemas for the stage-4 landing-page build spec.

The output is not a rendered page — it's a *build specification* a developer (or an AI
coding agent like Claude Code / Cursor) takes and turns into a real Next.js + Tailwind +
shadcn/ui repo. The shape mirrors the canonical example the team agreed on.

Design notes for keeping Gemini structured-output reliable:
- Avoid discriminated unions and deeply-nested polymorphism.
- Use `Literal` for fixed vocabularies (brand source, section classification, severities).
- Prefer `str` (markdown) for free-form prose chunks that the LLM does best — `copy_hooks`,
  `design_notes`, `component_recipe` — so the model isn't forced into rigid sub-structures
  for content the founder consumes as text anyway.
"""

from typing import Literal

from pydantic import BaseModel, Field

BrandSource = Literal["notebook", "synthesized", "user_questions"]
SectionClassification = Literal["core", "optional_included", "optional_skipped"]
KeywordPriority = Literal["high", "medium", "low"]


# ---------- Project brief --------------------------------------------------------


class SourcedText(BaseModel):
    """A claim paired with the upstream stages it came from. Used everywhere a fact in the
    spec needs traceability back to ideation / validation / gtm / brand."""

    text: str = Field(description="The claim itself, in plain prose.")
    sources: list[str] = Field(
        description=(
            "Short source tokens identifying where this claim came from. Use stage names "
            '("ideation", "validation", "gtm", "brand notebook") or more specific tags '
            '("validation.poll", "validation.Sara", "gtm.Persona1"). At least one entry.'
        ),
        min_length=1,
    )


class Persona(BaseModel):
    label: str = Field(description="Short persona name, ≤8 words. e.g. 'Pre-launch solo SaaS founders'.")
    description: str = Field(description="One-sentence description with demographics + behavior signals.")
    sources: list[str] = Field(description="Source tokens (see SourcedText.sources).", min_length=1)


class UserPain(BaseModel):
    label: str = Field(description="Pain in the founder's own words (or a faithful paraphrase). ≤12 words.")
    description: str = Field(description="One sentence expanding on the pain.")
    quantitative_evidence: str | None = Field(
        default=None,
        description=(
            "Numbers or counts that quantify the pain, if available. e.g. "
            '"41% of poll respondents, 4/4 interviewees". Null if only qualitative.'
        ),
    )
    sources: list[str] = Field(description="Source tokens.", min_length=1)


class ProofPoint(BaseModel):
    kind: Literal["quantitative", "qualitative"]
    statement: str = Field(
        description="The proof point. For quantitative, include numbers. For qualitative, a direct quote."
    )
    sources: list[str] = Field(description="Source tokens.", min_length=1)


class ProjectBrief(BaseModel):
    product_name: SourcedText
    one_line_value_prop: SourcedText
    primary_persona: Persona
    secondary_persona: Persona | None = Field(
        default=None, description="Optional second ICP. Null if only one persona is clear from the inputs."
    )
    top_user_pains: list[UserPain] = Field(description="Three to five pains, ordered by severity.")
    top_features: list[str] = Field(
        description=(
            "Features in order of pull (what attracts the target persona most). Plain strings — no markdown — "
            "three to six entries."
        )
    )
    proof_points: list[ProofPoint] = Field(description="Two to six proof points mixing quantitative and qualitative.")


# ---------- Brand --------------------------------------------------------------


class BrandDirection(BaseModel):
    source: BrandSource = Field(
        description=(
            '"notebook" when the brand stage filled in all dimensions cleanly; "synthesized" when the spec '
            "is inferring from ideation/validation/gtm without explicit brand input; "
            '"user_questions" when key dimensions need to be confirmed by the founder.'
        ),
    )
    tone: SourcedText
    voice: SourcedText
    palette: SourcedText = Field(
        description=(
            "Color palette. Include hex codes when known. e.g. "
            '"warm monochrome — #0E0E0C off-black, #F6F2EA bone, #C5F33D lime accent for CTAs."'
        )
    )
    typography: SourcedText = Field(description="Font choices with usage. e.g. 'Geist Sans (headings) / Inter (body)'.")
    imagery: SourcedText = Field(description="Visual direction — what's allowed, what aesthetic.")
    references: SourcedText = Field(description="Three to five sites that nail the vibe.")
    anti_references: SourcedText = Field(description="Looks the page must NOT have. Be specific.")


# ---------- SEO + competitors ---------------------------------------------------


class SEOKeyword(BaseModel):
    phrase: str = Field(description="The search phrase, lowercase, no quotes.")
    sources: list[str] = Field(
        description=(
            'Where the keyword came from. e.g. "competitor:prefinery.com" or "search:waitlist tool referral". '
            "At least one."
        ),
        min_length=1,
    )
    priority: KeywordPriority


class CompetitorPositioning(BaseModel):
    name: str = Field(description="Company name.")
    url: str = Field(description="Primary URL. Copy from validation.report.competitors[].source_url verbatim.")
    pages_fetched: list[str] = Field(
        description=(
            "Paths that were (or would have been) inspected. e.g. ['/', '/pricing']. If unknown, default to ['/'] only."
        )
    )
    positioning: str = Field(description="One-sentence positioning statement.")
    icp: str = Field(description="Their stated or inferred target customer.")
    pricing: str = Field(description="Pricing summary. e.g. 'Free / Pro $24/mo / Business $74/mo'.")
    cta: str = Field(description="Primary CTA copy on their homepage. e.g. 'Start your free trial'.")
    voice_notes: str = Field(description="A few words on tone — 'friendly', 'enterprise', 'developer-y', etc.")


class CoverageGap(BaseModel):
    competitor: str = Field(description="Competitor name we couldn't fully cover.")
    url: str | None = Field(default=None, description="URL that failed to yield content.")
    reason: str = Field(description="What failed. e.g. 'Heavy client-side JS, empty content via static fetch'.")


# ---------- Page structure ------------------------------------------------------


class PageSection(BaseModel):
    number: int = Field(description="Section order. Start at 1, monotonically increasing.")
    name: str = Field(description="Section name. e.g. 'Hero', 'Pricing', 'Comparison table'.")
    classification: SectionClassification = Field(
        description=(
            '"core" for sections present on essentially every landing page (nav, hero, social proof, '
            'features, how-it-works, pricing, FAQ, final CTA, footer). "optional_included" when an optional '
            "section (problem statement, use cases, comparison table) was added for a justified reason. "
            '"optional_skipped" is not used here — those go in `skipped_sections` instead.'
        )
    )
    why_included: str | None = Field(
        default=None,
        description=(
            "REQUIRED if classification is 'optional_included'. One short paragraph citing the upstream "
            "data that justifies including this optional section. Null for core sections."
        ),
    )
    purpose: str = Field(description="One short sentence on what this section is for from the visitor's POV.")
    copy_hooks: str = Field(
        description=(
            "Concrete copy: section eyebrow, H1/H2, supporting text, CTA labels. Use markdown bullets and "
            "**bold** to emphasize headings within the copy. The founder should be able to read this and "
            "ship the copy as-is."
        )
    )
    design_notes: str = Field(
        description=(
            "Layout + styling specifics. Tailwind class hints (`grid grid-cols-3`), responsive behavior, "
            "image treatment, spacing scale. Markdown bullets OK."
        )
    )
    component_recipe: str = Field(
        description=(
            "Which shadcn/ui (or other) components to compose, in markdown bullets or a short prose list. "
            "e.g. '<Card> + <CardHeader> + <Button variant=\"default\">'."
        )
    )
    posthog_events: list[str] = Field(
        description=(
            "Event signatures fired from this section. e.g. "
            '`cta_clicked { location: "hero", label: "Start free" }`. Empty list if only autocapture.'
        )
    )
    acceptance_criteria: list[str] = Field(
        description="Three to six acceptance criteria. Each is a single declarative sentence."
    )


class SkippedSection(BaseModel):
    name: str
    reason: str = Field(description="Why this section was skipped. Be honest — cite the upstream gap.")


# ---------- Tail (SEO, perf, instrumentation, acceptance, appendix) --------------


class SEOFrontMatter(BaseModel):
    title: str = Field(description="<title> tag content. ≤60 characters. Embed the primary keyword.", max_length=60)
    description: str = Field(
        description='<meta name="description"> content. 130-160 characters. Embed a secondary keyword.',
        max_length=160,
    )
    og_image_alt: str | None = Field(default=None, description="Alt text for the og:image. Brief, image-describing.")
    json_ld_type: str = Field(description='Schema.org type for JSON-LD. e.g. "SoftwareApplication".')


class PerformanceFloor(BaseModel):
    lcp_max_seconds: float = Field(default=2.5, description="Largest Contentful Paint ceiling, 4G simulated.")
    cls_max: float = Field(default=0.1, description="Cumulative Layout Shift ceiling.")
    lighthouse_a11y_min: int = Field(default=95, description="Minimum Lighthouse a11y score.")
    notes: list[str] = Field(
        default_factory=list,
        description="Implementation notes for hitting the targets — image priority, font loading, etc.",
    )


class PostHogCustomEvent(BaseModel):
    name: str = Field(description="Snake_case event name, e.g. 'cta_clicked'.")
    when: str = Field(description="When the event fires, plain language.")
    properties: list[str] = Field(
        description="Property names, optional with '?' suffix. e.g. ['location', 'label', 'plan?']."
    )


class InstrumentationGuide(BaseModel):
    sdk_install_cmd: str = Field(
        default="npx @posthog/wizard@latest",
        description="One-line shell command for SDK setup.",
    )
    init_notes: list[str] = Field(
        description="Bullet points for posthog.init overrides — autocapture, persistence, session replay masking, etc."
    )
    identify_notes: list[str] = Field(
        description="When and how to call posthog.identify — typically on signup completion."
    )
    custom_events: list[PostHogCustomEvent] = Field(description="Custom events beyond autocapture.")
    privacy_notes: list[str] = Field(
        default_factory=list,
        description="DNT handling, PII boundaries, paths that should disable session replay.",
    )


class GlobalAcceptanceCriterion(BaseModel):
    statement: str = Field(description="A single, testable statement. e.g. 'Lighthouse a11y ≥ 95'.")


# ---------- Top-level spec ------------------------------------------------------


class LandingPageBuildSpec(BaseModel):
    """Full structured build spec. Stored as JSON on FounderProject.mvp.page.

    Note the field is still called `page` on the envelope so the frontend doesn't need to
    relearn the shape — the meaning shifted from 'rendered page' to 'spec for the page'.
    """

    project_name: str = Field(description="Founder's project name, as it appears on the FounderProject row.")

    tldr: list[str] = Field(
        description=(
            "Three to six punchy bullets summarizing what this spec contains: project + ICPs + top keywords "
            "+ brand direction + sections included/skipped + competitors covered. Markdown bullets OK."
        )
    )

    project_brief: ProjectBrief
    brand: BrandDirection
    seo_keywords: list[SEOKeyword] = Field(description="Six to twelve keywords. Sort by priority.")
    competitor_profiles: list[CompetitorPositioning] = Field(
        description=("One entry per real competitor in validation.report.competitors. Skip any with no source_url.")
    )
    coverage_gaps: list[CoverageGap] = Field(
        default_factory=list,
        description=(
            "Competitors we couldn't profile fully. Empty list if every validation competitor had a usable URL."
        ),
    )

    page_sections: list[PageSection] = Field(
        description=(
            "Ordered list of sections to build. Always include core sections in this order: Nav, Hero, "
            "Social proof, Features, How it works, Pricing, FAQ, Final CTA, Footer. Insert optional sections "
            "(Problem statement, Use cases, Comparison table) where justified."
        )
    )
    skipped_sections: list[SkippedSection] = Field(
        default_factory=list,
        description="Optional sections that were deliberately omitted, with reason citing the upstream gap.",
    )

    seo_front_matter: SEOFrontMatter
    performance_floor: PerformanceFloor
    instrumentation: InstrumentationGuide
    global_acceptance_criteria: list[GlobalAcceptanceCriterion] = Field(
        description="Six to twelve global criteria — performance, a11y, instrumentation, brand consistency."
    )
