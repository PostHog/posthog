/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `ideation` - Ideation
 * `validation` - Validation
 * `gtm` - Gtm
 * `mvp` - Mvp
 * `marketing` - Marketing
 */
export type CurrentStepEnumApi = (typeof CurrentStepEnumApi)[keyof typeof CurrentStepEnumApi]

export const CurrentStepEnumApi = {
    Ideation: 'ideation',
    Validation: 'validation',
    Gtm: 'gtm',
    Mvp: 'mvp',
    Marketing: 'marketing',
} as const

/**
 * The shape of stage 1 output that validation consumes. Mirrors the JSON column on CofounderProject.
 */
export interface IdeationInputApi {
    /** The product or service the founder wants to build. */
    what: string
    /** How the product works — the mechanism, technology, or delivery model. */
    how: string
    /** The target customer or user segment. */
    who: string
    /** The problem this solves and why it matters to the target customer. */
    problem: string
}

export interface CompetitorApi {
    /** The actual company name. Be specific — no generic categories. */
    name: string
    /** One sentence on what they do. */
    description: string
    /** How they go to market — pricing, channel, target segment. */
    positioning: string
    /** Rough pricing if publicly known; null otherwise. */
    pricing?: string | null
    /** What they do well (max 3 bullets). */
    strengths: string[]
    /** Where they fall short (max 3 bullets). */
    weaknesses: string[]
    /** Primary URL cited in the research findings for this competitor (homepage, pricing page, or press article). Null if no source was cited. Must be one of the URLs that appeared in the research findings — do not invent URLs. */
    source_url?: string | null
}

export interface DifferentiationApi {
    /** One-line "we are X for Y" positioning vs the competitive landscape. */
    summary: string
    /** What makes this defensible long-term. If unclear, return "unclear" and explain why. */
    moat: string
    /** The specific gap existing players miss that this idea fills. */
    gap_in_market: string
}

export type FounderModeLevelEnumApi = (typeof FounderModeLevelEnumApi)[keyof typeof FounderModeLevelEnumApi]

export const FounderModeLevelEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
} as const

export interface AssumptionApi {
    /** A single testable assumption that must be true for the idea to work. */
    statement: string
    /** What breaks if this assumption is wrong. */
    risk_if_false: string
    /** Honest assessment of how much evidence currently supports this assumption. */
    current_confidence: FounderModeLevelEnumApi
}

export interface ValidationExperimentApi {
    /** Zero-indexed position of the assumption this experiment tests. */
    assumption_index: number
    /** Short label for the experiment (3-6 words). */
    name: string
    /** Concrete steps the founder runs. Should be actionable today. */
    description: string
    /** Cost in dollars and time, e.g. "$0, 2 hours" or "$200, 1 week". */
    cost_estimate: string
    /** What outcome would tell the founder the assumption holds. */
    success_signal: string
}

export type RiskCategoryEnumApi = (typeof RiskCategoryEnumApi)[keyof typeof RiskCategoryEnumApi]

export const RiskCategoryEnumApi = {
    Market: 'market',
    Technical: 'technical',
    Regulatory: 'regulatory',
    Execution: 'execution',
    Timing: 'timing',
    Other: 'other',
} as const

export interface RiskApi {
    /** Which dimension this risk lives in. */
    category: RiskCategoryEnumApi
    /** Specific risk — not generic. Name the actual failure mode. */
    description: string
    /** How damaging if it materializes. */
    severity: FounderModeLevelEnumApi
}

export interface VerdictApi {
    /**
     * Overall 1-10 score weighing market, defensibility, and feasibility.
     * @minimum 1
     * @maximum 10
     */
    score: number
    /** How confident in this score given the information provided. */
    confidence: FounderModeLevelEnumApi
    /** One short paragraph explaining the score. Honest, not flattering. */
    reasoning: string
    /** Three to five concrete actions the founder should take next, ordered by priority. */
    next_steps: string[]
}

/**
 * The full structured output the LLM produces. Stored as JSON on ValidationReport.report.
 */
export interface ValidationReportApi {
    /** Three to six real competitors, direct and indirect. */
    competitors: CompetitorApi[]
    differentiation: DifferentiationApi
    /** Three to five critical assumptions ordered by riskiness, riskiest first. */
    assumptions: AssumptionApi[]
    /** One concrete validation experiment per assumption, indexed by assumption_index. */
    experiments: ValidationExperimentApi[]
    /** Three to six top risks across the listed categories. */
    risks: RiskApi[]
    verdict: VerdictApi
}

/**
 * API-facing envelope for the `validation` JSON column.

Drives the generated TypeScript + Zod types via drf-spectacular → Orval. The Celery task
is the sole writer; clients are read-only and poll until `status` is terminal.
 */
export interface ValidationEnvelopeApi {
    /** Lifecycle state of the validation run. */
    status?: 'pending' | 'running' | 'completed' | 'failed' | null
    /** Which Gemini pass is currently in flight while `status='running'`. Null otherwise. */
    current_pass?: 'research' | 'synthesis' | null
    /** The synthesized validation output. Present once `status='completed'`. */
    report?: ValidationReportApi | null
    /** SHA-256 of the ideation payload at the time this run started. Used by clients to detect a stale report after the founder edits ideation. */
    ideation_hash?: string | null
    /** ISO timestamp when the run kicked off. */
    started_at?: string | null
    /** ISO timestamp when the run finished successfully. */
    completed_at?: string | null
    /** ISO timestamp when the run failed. */
    failed_at?: string | null
    /** Trace id linking to the underlying LLM calls in PostHog LLM analytics. */
    trace_id?: string | null
    /** Human-readable error message when `status='failed'`. Empty otherwise. */
    error?: string
}

export interface TargetSegmentApi {
    /** Short label for this audience segment (e.g. 'Solo SaaS founders, pre-launch'). */
    name: string
    /** Who they are, where they hang out, what they care about, what signals identify them. */
    description: string
    /** Why this segment is reachable and buyable right now — concrete, time-anchored reasoning. */
    why_reachable_now: string
}

export interface PricingTierApi {
    /** Tier name (e.g. Free, Pro, Team, Enterprise). */
    name: string
    /** Price point with cadence and currency (e.g. '$29/mo', '$0', 'Contact us'). */
    price: string
    /** Which TargetSegment this tier is aimed at — reference by name. */
    target_segment: string
    /** What the founder is selling at this tier in plain language. */
    value: string
}

export interface GTMSummaryApi {
    /** One-paragraph positioning: who it's for, what category, what makes it different. Should read like a founder-voice deck slide, not marketing copy. */
    positioning_statement: string
    /** The wedge audience — the single segment the founder should chase first. */
    primary_segment: TargetSegmentApi
    /** 1-3 adjacent segments to expand into once the primary wedge is proven. */
    secondary_segments: TargetSegmentApi[]
    /** Where this plays. New category, existing category, or wedge inside an existing category. */
    category: string
    /** What makes this defensible over a 12-24 month horizon — be specific, not 'network effects'. */
    moat: string
    /** How this should be priced and why — per-seat vs usage vs flat vs freemium, and the reasoning. */
    pricing_philosophy: string
    /** 2-4 concrete pricing tiers ordered low to high. */
    pricing_tiers: PricingTierApi[]
    /** The single highest-leverage acquisition channel — community, content, paid, partnerships, or sales-led. */
    primary_channel: string
    /** 2-4 supporting channels in priority order. */
    secondary_channels: string[]
}

/**
 * API-facing envelope for the `gtm` JSON column.
 */
export interface GTMEnvelopeApi {
    /** Lifecycle state of the GTM generation run. */
    status?: 'pending' | 'running' | 'completed' | 'failed' | null
    /** The synthesized GTM summary. Present once `status='completed'`. */
    result?: GTMSummaryApi | null
    /** ISO timestamp when the run kicked off. */
    started_at?: string | null
    /** ISO timestamp when the run finished successfully. */
    completed_at?: string | null
    /** ISO timestamp when the run failed. */
    failed_at?: string | null
    /** Trace id linking to the underlying LLM calls. */
    trace_id?: string | null
    /** Human-readable error message when `status='failed'`. Empty otherwise. */
    error?: string
}

export interface HappyPathStepApi {
    /** 1-indexed step number in the user journey. */
    step: number
    /** What the user does at this step — concrete, observable. */
    user_action: string
    /** What the product does in response — concrete, observable. */
    system_response: string
    /** How we know this step worked — what the user sees, what gets logged, what state changes. */
    success_signal: string
}

export interface MVPHappyPathApi {
    /** One sentence describing what the MVP does end-to-end. No marketing language. */
    one_liner: string
    /** 3-7 step happy-path user journey from first touch to value delivered. */
    core_flow: HappyPathStepApi[]
    /** Features that must ship in v1 to make the happy path work. */
    must_haves: string[]
    /** Features explicitly NOT in v1 — the anti-bloat list. Each entry is one feature with a one-line reason. */
    deliberately_excluded: string[]
}

/**
 * API-facing envelope for the `mvp` JSON column.
 */
export interface MVPEnvelopeApi {
    /** Lifecycle state of the MVP generation run. */
    status?: 'pending' | 'running' | 'completed' | 'failed' | null
    /** The MVP happy-path spec. Present once `status='completed'`. */
    result?: MVPHappyPathApi | null
    /** ISO timestamp when the run kicked off. */
    started_at?: string | null
    /** ISO timestamp when the run finished successfully. */
    completed_at?: string | null
    /** ISO timestamp when the run failed. */
    failed_at?: string | null
    /** Trace id linking to the underlying LLM calls. */
    trace_id?: string | null
    /** Human-readable error message when `status='failed'`. Empty otherwise. */
    error?: string
}

/**
 * A claim paired with the upstream stages it came from. Used everywhere a fact in the
spec needs traceability back to ideation / validation / gtm / brand.
 */
export interface SourcedTextApi {
    /** The claim itself, in plain prose. */
    text: string
    /**
     * Short source tokens identifying where this claim came from. Use stage names ("ideation", "validation", "gtm", "brand notebook") or more specific tags ("validation.poll", "validation.Sara", "gtm.Persona1"). At least one entry.
     * @minItems 1
     */
    sources: string[]
}

export interface PersonaApi {
    /** Short persona name, ≤8 words. e.g. 'Pre-launch solo SaaS founders'. */
    label: string
    /** One-sentence description with demographics + behavior signals. */
    description: string
    /**
     * Source tokens (see SourcedText.sources).
     * @minItems 1
     */
    sources: string[]
}

export interface UserPainApi {
    /** Pain in the founder's own words (or a faithful paraphrase). ≤12 words. */
    label: string
    /** One sentence expanding on the pain. */
    description: string
    /** Numbers or counts that quantify the pain, if available. e.g. "41% of poll respondents, 4/4 interviewees". Null if only qualitative. */
    quantitative_evidence?: string | null
    /**
     * Source tokens.
     * @minItems 1
     */
    sources: string[]
}

export type ProofPointKindEnumApi = (typeof ProofPointKindEnumApi)[keyof typeof ProofPointKindEnumApi]

export const ProofPointKindEnumApi = {
    Quantitative: 'quantitative',
    Qualitative: 'qualitative',
} as const

export interface ProofPointApi {
    kind: ProofPointKindEnumApi
    /** The proof point. For quantitative, include numbers. For qualitative, a direct quote. */
    statement: string
    /**
     * Source tokens.
     * @minItems 1
     */
    sources: string[]
}

export interface ProjectBriefApi {
    product_name: SourcedTextApi
    one_line_value_prop: SourcedTextApi
    primary_persona: PersonaApi
    /** Optional second ICP. Null if only one persona is clear from the inputs. */
    secondary_persona?: PersonaApi | null
    /** Three to five pains, ordered by severity. */
    top_user_pains: UserPainApi[]
    /** Features in order of pull (what attracts the target persona most). Plain strings — no markdown — three to six entries. */
    top_features: string[]
    /** Two to six proof points mixing quantitative and qualitative. */
    proof_points: ProofPointApi[]
}

export type BrandDirectionSourceEnumApi = (typeof BrandDirectionSourceEnumApi)[keyof typeof BrandDirectionSourceEnumApi]

export const BrandDirectionSourceEnumApi = {
    Notebook: 'notebook',
    Synthesized: 'synthesized',
    UserQuestions: 'user_questions',
} as const

export interface BrandDirectionApi {
    /** "notebook" when the brand stage filled in all dimensions cleanly; "synthesized" when the spec is inferring from ideation/validation/gtm without explicit brand input; "user_questions" when key dimensions need to be confirmed by the founder. */
    source: BrandDirectionSourceEnumApi
    tone: SourcedTextApi
    voice: SourcedTextApi
    /** Color palette. Include hex codes when known. e.g. "warm monochrome — #0E0E0C off-black, #F6F2EA bone, #C5F33D lime accent for CTAs." */
    palette: SourcedTextApi
    /** Font choices with usage. e.g. 'Geist Sans (headings) / Inter (body)'. */
    typography: SourcedTextApi
    /** Visual direction — what's allowed, what aesthetic. */
    imagery: SourcedTextApi
    /** Three to five sites that nail the vibe. */
    references: SourcedTextApi
    /** Looks the page must NOT have. Be specific. */
    anti_references: SourcedTextApi
}

export interface SEOKeywordApi {
    /** The search phrase, lowercase, no quotes. */
    phrase: string
    /**
     * Where the keyword came from. e.g. "competitor:prefinery.com" or "search:waitlist tool referral". At least one.
     * @minItems 1
     */
    sources: string[]
    priority: FounderModeLevelEnumApi
}

export interface CompetitorPositioningApi {
    /** Company name. */
    name: string
    /** Primary URL. Copy from validation.report.competitors[].source_url verbatim. */
    url: string
    /** Paths that were (or would have been) inspected. e.g. ['/', '/pricing']. If unknown, default to ['/'] only. */
    pages_fetched: string[]
    /** One-sentence positioning statement. */
    positioning: string
    /** Their stated or inferred target customer. */
    icp: string
    /** Pricing summary. e.g. 'Free / Pro $24/mo / Business $74/mo'. */
    pricing: string
    /** Primary CTA copy on their homepage. e.g. 'Start your free trial'. */
    cta: string
    /** A few words on tone — 'friendly', 'enterprise', 'developer-y', etc. */
    voice_notes: string
}

export interface CoverageGapApi {
    /** Competitor name we couldn't fully cover. */
    competitor: string
    /** URL that failed to yield content. */
    url?: string | null
    /** What failed. e.g. 'Heavy client-side JS, empty content via static fetch'. */
    reason: string
}

export type ClassificationEnumApi = (typeof ClassificationEnumApi)[keyof typeof ClassificationEnumApi]

export const ClassificationEnumApi = {
    Core: 'core',
    OptionalIncluded: 'optional_included',
    OptionalSkipped: 'optional_skipped',
} as const

export interface PageSectionApi {
    /** Section order. Start at 1, monotonically increasing. */
    number: number
    /** Section name. e.g. 'Hero', 'Pricing', 'Comparison table'. */
    name: string
    /** "core" for sections present on essentially every landing page (nav, hero, social proof, features, how-it-works, pricing, FAQ, final CTA, footer). "optional_included" when an optional section (problem statement, use cases, comparison table) was added for a justified reason. "optional_skipped" is not used here — those go in `skipped_sections` instead. */
    classification: ClassificationEnumApi
    /** REQUIRED if classification is 'optional_included'. One short paragraph citing the upstream data that justifies including this optional section. Null for core sections. */
    why_included?: string | null
    /** One short sentence on what this section is for from the visitor's POV. */
    purpose: string
    /** Concrete copy: section eyebrow, H1/H2, supporting text, CTA labels. Use markdown bullets and **bold** to emphasize headings within the copy. The founder should be able to read this and ship the copy as-is. */
    copy_hooks: string
    /** Layout + styling specifics. Tailwind class hints (`grid grid-cols-3`), responsive behavior, image treatment, spacing scale. Markdown bullets OK. */
    design_notes: string
    /** Which shadcn/ui (or other) components to compose, in markdown bullets or a short prose list. e.g. '<Card> + <CardHeader> + <Button variant="default">'. */
    component_recipe: string
    /** Event signatures fired from this section. e.g. `cta_clicked { location: "hero", label: "Start free" }`. Empty list if only autocapture. */
    posthog_events: string[]
    /** Three to six acceptance criteria. Each is a single declarative sentence. */
    acceptance_criteria: string[]
}

export interface SkippedSectionApi {
    name: string
    /** Why this section was skipped. Be honest — cite the upstream gap. */
    reason: string
}

export interface SEOFrontMatterApi {
    /**
     * <title> tag content. ≤60 characters. Embed the primary keyword.
     * @maxLength 60
     */
    title: string
    /**
     * <meta name="description"> content. 130-160 characters. Embed a secondary keyword.
     * @maxLength 160
     */
    description: string
    /** Alt text for the og:image. Brief, image-describing. */
    og_image_alt?: string | null
    /** Schema.org type for JSON-LD. e.g. "SoftwareApplication". */
    json_ld_type: string
}

export interface PerformanceFloorApi {
    /** Largest Contentful Paint ceiling, 4G simulated. */
    lcp_max_seconds?: number
    /** Cumulative Layout Shift ceiling. */
    cls_max?: number
    /** Minimum Lighthouse a11y score. */
    lighthouse_a11y_min?: number
    /** Implementation notes for hitting the targets — image priority, font loading, etc. */
    notes?: string[]
}

export interface PostHogCustomEventApi {
    /** Snake_case event name, e.g. 'cta_clicked'. */
    name: string
    /** When the event fires, plain language. */
    when: string
    /** Property names, optional with '?' suffix. e.g. ['location', 'label', 'plan?']. */
    properties: string[]
}

export interface InstrumentationGuideApi {
    /** One-line shell command for SDK setup. */
    sdk_install_cmd?: string
    /** Bullet points for posthog.init overrides — autocapture, persistence, session replay masking, etc. */
    init_notes: string[]
    /** When and how to call posthog.identify — typically on signup completion. */
    identify_notes: string[]
    /** Custom events beyond autocapture. */
    custom_events: PostHogCustomEventApi[]
    /** DNT handling, PII boundaries, paths that should disable session replay. */
    privacy_notes?: string[]
}

export interface GlobalAcceptanceCriterionApi {
    /** A single, testable statement. e.g. 'Lighthouse a11y ≥ 95'. */
    statement: string
}

/**
 * Full structured build spec. Stored as JSON on FounderProject.mvp.page.

Note the field is still called `page` on the envelope so the frontend doesn't need to
relearn the shape — the meaning shifted from 'rendered page' to 'spec for the page'.
 */
export interface LandingPageBuildSpecApi {
    /** Founder's project name, as it appears on the FounderProject row. */
    project_name: string
    /** Three to six punchy bullets summarizing what this spec contains: project + ICPs + top keywords + brand direction + sections included/skipped + competitors covered. Markdown bullets OK. */
    tldr: string[]
    project_brief: ProjectBriefApi
    brand: BrandDirectionApi
    /** Six to twelve keywords. Sort by priority. */
    seo_keywords: SEOKeywordApi[]
    /** One entry per real competitor in validation.report.competitors. Skip any with no source_url. */
    competitor_profiles: CompetitorPositioningApi[]
    /** Competitors we couldn't profile fully. Empty list if every validation competitor had a usable URL. */
    coverage_gaps?: CoverageGapApi[]
    /** Ordered list of sections to build. Always include core sections in this order: Nav, Hero, Social proof, Features, How it works, Pricing, FAQ, Final CTA, Footer. Insert optional sections (Problem statement, Use cases, Comparison table) where justified. */
    page_sections: PageSectionApi[]
    /** Optional sections that were deliberately omitted, with reason citing the upstream gap. */
    skipped_sections?: SkippedSectionApi[]
    seo_front_matter: SEOFrontMatterApi
    performance_floor: PerformanceFloorApi
    instrumentation: InstrumentationGuideApi
    /** Six to twelve global criteria — performance, a11y, instrumentation, brand consistency. */
    global_acceptance_criteria: GlobalAcceptanceCriterionApi[]
}

/**
 * API-facing envelope for the `marketing_page` JSON column.

Field is still called `page` (not `result`) — the value is the *spec* for the landing
page, named for what the founder ends up shipping rather than the generation step.
 */
export interface MarketingPageEnvelopeApi {
    /** Lifecycle state of the landing page generation run. */
    status?: 'pending' | 'running' | 'completed' | 'failed' | null
    /** The landing page build spec. Present once `status='completed'`. */
    page?: LandingPageBuildSpecApi | null
    /** ISO timestamp when the run kicked off. */
    started_at?: string | null
    /** ISO timestamp when the run finished successfully. */
    completed_at?: string | null
    /** ISO timestamp when the run failed. */
    failed_at?: string | null
    /** Trace id linking to the underlying LLM calls. */
    trace_id?: string | null
    /** Human-readable error message when `status='failed'`. Empty otherwise. */
    error?: string
}

export interface SocialPostApi {
    /** Platform: 'linkedin', 'twitter', 'reddit', 'indie_hackers', or 'hacker_news'. */
    platform: string
    /** Full post text, ready to copy-paste and publish. */
    content: string
    /** Timing and format tips for this specific post. */
    tips: string
}

export interface PracticalStepApi {
    /** Short title for the action (e.g. 'Hunter outreach for Product Hunt launch'). */
    title: string
    /** What to do and why it matters. */
    description: string
    /** Where this happens (e.g. 'Product Hunt', 'LinkedIn', 'Twitter/X', 'Reddit'). */
    channel: string
    /** When to do this relative to launch day (e.g. 'D-7', 'Launch day', 'D+1'). */
    timeline: string
    /** Pre-written posts for this step (may be empty). */
    ready_to_use_content: SocialPostApi[]
}

export interface PracticalStepsResultApi {
    /** 2-3 sentence overview of the launch strategy. */
    launch_summary: string
    /** Specific communities where the target audience hangs out (e.g. subreddits, Discord servers, Slack groups). */
    target_communities: string[]
    /** Ordered list of launch actions, chronological from pre-launch to post-launch. */
    steps: PracticalStepApi[]
}

/**
 * API-facing envelope for the `marketing_steps` JSON column.
 */
export interface MarketingStepsEnvelopeApi {
    /** Lifecycle state of the practical steps generation run. */
    status?: 'pending' | 'running' | 'completed' | 'failed' | null
    /** The launch playbook. Present once `status='completed'`. */
    result?: PracticalStepsResultApi | null
    /** ISO timestamp when the run kicked off. */
    started_at?: string | null
    /** ISO timestamp when the run finished successfully. */
    completed_at?: string | null
    /** ISO timestamp when the run failed. */
    failed_at?: string | null
    /** Trace id linking to the underlying LLM calls. */
    trace_id?: string | null
    /** Human-readable error message when `status='failed'`. Empty otherwise. */
    error?: string
}

export interface RepoLinkApi {
    /** API URL of the repository (`https://api.github.com/repos/<owner>/<name>`). */
    repo_url: string
    /** Browseable URL of the repository the founder can open in their browser. */
    html_url: string
    /** The default branch the initial commit landed on (typically `main`). */
    default_branch: string
    /** SHA of the initial commit containing every generated file. */
    commit_sha: string
    /** How many files were pushed in the initial commit. */
    file_count: number
}

/**
 * GitHub Pages site metadata returned after enablement + provisioning.
 */
export interface PagesLinkApi {
    /** Live URL the static page is served at, e.g. https://owner.github.io/repo/ */
    html_url: string
    /** GitHub Pages build state at the time of polling: `built`, `building`, `queued`, `errored`, or `not_provisioned` if we gave up polling before it went live. */
    pages_status: string
    /** Branch GitHub Pages serves from (e.g. `main`). */
    source_branch: string
    /** Path within the branch the site is served from (e.g. `/`). */
    source_path: string
}

/**
 * Generated file tree as `{path: contents}`. Populated by `run_scaffold`. Paths are POSIX-style relative paths (no leading slash). Null while pending or before the first generation run.
 */
export type ScaffoldEnvelopeApiFiles = { [key: string]: string } | null

/**
 * API-facing envelope for the `scaffold` JSON column.
 */
export interface ScaffoldEnvelopeApi {
    /** Lifecycle state of the most recent scaffold action. */
    status?: 'pending' | 'running' | 'completed' | 'failed' | null
    /** Generated file tree as `{path: contents}`. Populated by `run_scaffold`. Paths are POSIX-style relative paths (no leading slash). Null while pending or before the first generation run. */
    files?: ScaffoldEnvelopeApiFiles
    /** Number of files in `files`. */
    file_count?: number | null
    /** Total size of all file contents combined. */
    total_bytes?: number | null
    /** Populated by `publish_scaffold` once the file tree has been pushed to GitHub. */
    repo?: RepoLinkApi | null
    /** Populated by `publish_scaffold` after enabling GitHub Pages on the new repo. `pages.html_url` is the live URL the founder can share. */
    pages?: PagesLinkApi | null
    /** ISO timestamp when the most recent action kicked off. */
    started_at?: string | null
    /** ISO timestamp when the most recent action succeeded. */
    completed_at?: string | null
    /** ISO timestamp when the most recent action failed. */
    failed_at?: string | null
    /** Trace id linking to the underlying operation. */
    trace_id?: string | null
    /** Human-readable error message when `status='failed'`. Empty otherwise. */
    error?: string
}

export interface FounderProjectApi {
    readonly id: string
    /**
     * Founder-chosen label for the startup idea, e.g. "AI-powered HOA management".
     * @maxLength 200
     */
    name: string
    /** Which stage the founder is currently on. One of: ideation, validation, gtm, mvp, marketing. Updated server-side when stages are kicked off, and can be PATCHed by the frontend.

  * `ideation` - Ideation
  * `validation` - Validation
  * `gtm` - Gtm
  * `mvp` - Mvp
  * `marketing` - Marketing */
    current_step?: CurrentStepEnumApi
    /** Stage 1 output. Shape: {what, how, who, problem}. Writing here triggers the validation Celery task asynchronously. */
    ideation?: IdeationInputApi
    /** Stable SHA-256 of the current ideation payload. Clients compare this to `validation.ideation_hash` to detect a stale report (founder edited ideation since the last validation run). */
    readonly ideation_hash: string
    /** Stage 2 envelope, server-managed. Triggered via the `run_validation` action. Clients poll the detail endpoint while status is `pending` or `running`. */
    readonly validation: ValidationEnvelopeApi
    /** Stage 3 envelope, server-managed. Conceptual GTM summary (positioning, target segments, pricing tiers, channels). Triggered via the `run_gtm` action. */
    readonly gtm: GTMEnvelopeApi
    /** Stage 4 envelope, server-managed. MVP happy-path spec (one-liner, core flow, must-haves, deliberately-excluded). Triggered via the `run_mvp` action. Schema is a placeholder and may change. */
    readonly mvp: MVPEnvelopeApi
    /** Stage 5a envelope, server-managed. Landing page build spec (copy hooks, design notes, shadcn/ui recipes, PostHog events, acceptance criteria). Triggered via the `run_landing_page` action. */
    readonly marketing_page: MarketingPageEnvelopeApi
    /** Stage 5b envelope, server-managed. Practical launch playbook with ready-to-publish posts for Product Hunt, LinkedIn, Twitter, Reddit, HN, etc. Triggered via the `run_practical_steps` action. */
    readonly marketing_steps: MarketingStepsEnvelopeApi
    /** Stage 6 envelope, server-managed. Two-step pipeline: `run_scaffold` renders the landing page spec into a single-page static site (`scaffold.files`), then `publish_scaffold` pushes it to a new GitHub repo AND enables GitHub Pages on the repo (`scaffold.repo` + `scaffold.pages` with the live URL). */
    readonly scaffold: ScaffoldEnvelopeApi
    /** The user who created this founder project. Set automatically on create. */
    readonly created_by: number
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedFounderProjectListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FounderProjectApi[]
}

export interface PatchedFounderProjectApi {
    readonly id?: string
    /**
     * Founder-chosen label for the startup idea, e.g. "AI-powered HOA management".
     * @maxLength 200
     */
    name?: string
    /** Which stage the founder is currently on. One of: ideation, validation, gtm, mvp, marketing. Updated server-side when stages are kicked off, and can be PATCHed by the frontend.

  * `ideation` - Ideation
  * `validation` - Validation
  * `gtm` - Gtm
  * `mvp` - Mvp
  * `marketing` - Marketing */
    current_step?: CurrentStepEnumApi
    /** Stage 1 output. Shape: {what, how, who, problem}. Writing here triggers the validation Celery task asynchronously. */
    ideation?: IdeationInputApi
    /** Stable SHA-256 of the current ideation payload. Clients compare this to `validation.ideation_hash` to detect a stale report (founder edited ideation since the last validation run). */
    readonly ideation_hash?: string
    /** Stage 2 envelope, server-managed. Triggered via the `run_validation` action. Clients poll the detail endpoint while status is `pending` or `running`. */
    readonly validation?: ValidationEnvelopeApi
    /** Stage 3 envelope, server-managed. Conceptual GTM summary (positioning, target segments, pricing tiers, channels). Triggered via the `run_gtm` action. */
    readonly gtm?: GTMEnvelopeApi
    /** Stage 4 envelope, server-managed. MVP happy-path spec (one-liner, core flow, must-haves, deliberately-excluded). Triggered via the `run_mvp` action. Schema is a placeholder and may change. */
    readonly mvp?: MVPEnvelopeApi
    /** Stage 5a envelope, server-managed. Landing page build spec (copy hooks, design notes, shadcn/ui recipes, PostHog events, acceptance criteria). Triggered via the `run_landing_page` action. */
    readonly marketing_page?: MarketingPageEnvelopeApi
    /** Stage 5b envelope, server-managed. Practical launch playbook with ready-to-publish posts for Product Hunt, LinkedIn, Twitter, Reddit, HN, etc. Triggered via the `run_practical_steps` action. */
    readonly marketing_steps?: MarketingStepsEnvelopeApi
    /** Stage 6 envelope, server-managed. Two-step pipeline: `run_scaffold` renders the landing page spec into a single-page static site (`scaffold.files`), then `publish_scaffold` pushes it to a new GitHub repo AND enables GitHub Pages on the repo (`scaffold.repo` + `scaffold.pages` with the live URL). */
    readonly scaffold?: ScaffoldEnvelopeApi
    /** The user who created this founder project. Set automatically on create. */
    readonly created_by?: number
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Body for the `publish_scaffold` action.
 */
export interface PublishScaffoldRequestApi {
    /** GitHub personal access token with `repo` scope. Used once to create the repo and push the initial commit, then discarded — not persisted. If omitted, the server falls back to the `FOUNDER_MODE_GITHUB_PAT` env var (local-dev convenience). */
    github_token?: string | null
    /**
     * Name for the new repository on the authenticated user's account.
     * @minLength 1
     * @maxLength 100
     * @pattern ^[A-Za-z0-9_.-]+$
     */
    repo_name: string
    /**
     * Repository visibility. `public` or `private`. Defaults to private.
     * @pattern ^(public|private)$
     */
    visibility?: string
    /**
     * Optional one-line repo description.
     * @maxLength 350
     */
    description?: string
}

export type AuthorEnumApi = (typeof AuthorEnumApi)[keyof typeof AuthorEnumApi]

export const AuthorEnumApi = {
    Agent: 'agent',
    User: 'user',
} as const

/**
 * A prior message in this topic's mini-chat thread.
 */
export interface ChatMessageInputApi {
    author: AuthorEnumApi
    value: string
}

export type FounderModeEnumApi = (typeof FounderModeEnumApi)[keyof typeof FounderModeEnumApi]

export const FounderModeEnumApi = {
    TechnicalCofounder: 'technical_cofounder',
    CommercialCofounder: 'commercial_cofounder',
} as const

/**
 * What the frontend POSTs each turn of a topic's mini-chat.
 */
export interface TurnRequestApi {
    /** Which topic this mini-chat is about. Currently always "idea" (the ideation step). */
    topic: string
    /** What the cofounder must extract from this topic before it can be satisfied. Topic-specific — the frontend defines it. For the idea topic this describes the {what, how, who, problem} the validation pass needs, and tells the cofounder which keys `crystallized_value` must carry. */
    goal: string
    /** The founder's latest reply in this thread. */
    user_answer: string
    /** This topic's prior thread (everything before `user_answer`). Empty on the first turn. */
    messages?: ChatMessageInputApi[]
    /** Which half of the founding team the cofounder plays. Selects the mode block injected into the system prompt. Defaults to commercial so older clients still get a coherent persona. */
    founder_mode?: FounderModeEnumApi
}

/**
 * REQUIRED when `satisfied` is true; null otherwise. The distilled output of this topic's conversation. Shape is topic-defined by the request `goal`: for the idea topic the keys are `what`, `how`, `who`, `problem` — each a synthesized prose string (a tightened coherent retelling, not a verbatim quote). The frontend writes this straight into FounderProject.ideation.
 */
export type TurnResponseApiCrystallizedValue = { [key: string]: unknown } | null

/**
 * What the backend returns each turn.
 */
export interface TurnResponseApi {
    /**
     * The cofounder's next message — a sharp follow-up question or a declarative claim. ≤30 words for the question proper; ≤2 short sentences if there's a preamble. When `satisfied` is true this is a brief 'got it, moving on' beat.
     * @maxLength 400
     */
    agent_message: string
    /** True when the cofounder has genuinely extracted enough on this topic to move on. False means the thread continues and `agent_message` is a follow-up. Do not set this true on a thin or one-word answer just to advance. */
    satisfied?: boolean
    /** REQUIRED when `satisfied` is true; null otherwise. The distilled output of this topic's conversation. Shape is topic-defined by the request `goal`: for the idea topic the keys are `what`, `how`, `who`, `problem` — each a synthesized prose string (a tightened coherent retelling, not a verbatim quote). The frontend writes this straight into FounderProject.ideation. */
    crystallized_value?: TurnResponseApiCrystallizedValue
    /** Internal — what the cofounder noticed and what it still needs (or why it's now satisfied), 1-2 sentences. Not shown to the founder; logged for prompt tuning. */
    reasoning: string
}

export type FounderProjectsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
