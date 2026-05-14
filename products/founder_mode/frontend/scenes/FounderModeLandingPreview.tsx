import { SceneExport } from 'scenes/sceneTypes'

import type { LandingPageBuildSpec } from '../components/founderLandingPageLogic'
import { LandingPageMockup } from '../components/LandingPageMockup'

const MOCK_SPEC: LandingPageBuildSpec = {
    project_name: 'Founder Mode',
    tldr: [
        'Go from messy idea to launch-ready landing page in one afternoon.',
        'Guided chat fills your lean canvas, validates assumptions, and writes the build spec.',
        'Hand the spec to an AI coding agent and ship.',
    ],
    project_brief: {
        product_name: { text: 'Founder Mode', sources: [] },
        one_line_value_prop: {
            text: 'From idea to launch artifacts in one afternoon.',
            sources: [],
        },
        primary_persona: {
            label: 'first-time solo founders',
            description: 'in the first 90 days of an idea, still shaping what to build',
            sources: [],
        },
        secondary_persona: null,
        top_user_pains: [
            {
                label: 'Stuck before the first line of code',
                description: 'Three abandoned Notion docs about the same idea. No version feels committable.',
                quantitative_evidence: null,
                sources: [],
            },
            {
                label: 'Validation is hand-wavy',
                description:
                    'You know you should pressure-test assumptions, but you skip it and start building anyway.',
                quantitative_evidence: null,
                sources: [],
            },
            {
                label: 'Landing pages are a slog',
                description: "You can build the product but you can't bear writing the copy or designing the page.",
                quantitative_evidence: null,
                sources: [],
            },
        ],
        top_features: [
            'Guided lean canvas chat',
            'Automated validation pass',
            'Landing page build spec',
            'GTM plan generator',
            'PostHog instrumentation included',
            'Markdown export for any AI coding agent',
        ],
        proof_points: [
            {
                kind: 'qualitative',
                statement: '"I went from a vague Notion doc to a published landing page in a single afternoon."',
                sources: [],
            },
            {
                kind: 'quantitative',
                statement: '4 out of 5 founders interviewed said they would use this in week one of a new idea.',
                sources: [],
            },
            {
                kind: 'qualitative',
                statement: '"Don\'t give me a summary — give me artifacts I can ship. This does that."',
                sources: [],
            },
            {
                kind: 'quantitative',
                statement: 'Average time from idea to first published landing page: 1 working day.',
                sources: [],
            },
        ],
    },
    brand: {
        source: 'synthesized',
        tone: { text: 'Direct, founder-to-founder, no fluff.', sources: [] },
        voice: { text: 'Confident, pragmatic, occasionally dry.', sources: [] },
        palette: { text: 'Slate neutrals with a single emerald accent for affirmation.', sources: [] },
        typography: { text: 'System sans-serif, tight headings, generous line height in body.', sources: [] },
        imagery: { text: 'Screenshots of the artifacts being produced, not abstract illustrations.', sources: [] },
        references: { text: 'Linear, Vercel, Resend — sharp, opinionated tool aesthetics.', sources: [] },
        anti_references: {
            text: 'Generic SaaS hero illustrations, AI-themed gradients, stock photography.',
            sources: [],
        },
    },
    seo_keywords: [
        { phrase: 'idea to launch', priority: 'high', sources: [] },
        { phrase: 'lean canvas generator', priority: 'medium', sources: [] },
        { phrase: 'landing page for founders', priority: 'medium', sources: [] },
    ],
    competitor_profiles: [],
    coverage_gaps: [],
    page_sections: [
        {
            number: 1,
            name: 'Hero',
            classification: 'core',
            why_included: null,
            purpose: 'Land the value prop and get to a CTA in under 6 seconds.',
            copy_hooks: 'From idea to launch artifacts in one afternoon.',
            design_notes: 'Centered hero, gradient wash, two CTAs.',
            component_recipe: 'Standard hero with primary + secondary button.',
            posthog_events: ['$pageview', 'hero_cta_clicked'],
            acceptance_criteria: ['Headline visible without scroll on 1280×800.'],
        },
        {
            number: 2,
            name: 'Pain points',
            classification: 'core',
            why_included: null,
            purpose: 'Earn trust by naming the problems out loud.',
            copy_hooks: 'Built for the headaches you actually have.',
            design_notes: '3-up card grid, neutral background.',
            component_recipe: 'Card grid component.',
            posthog_events: ['$pageview'],
            acceptance_criteria: ['Three cards visible on desktop, stack on mobile.'],
        },
    ],
    skipped_sections: [],
    seo_front_matter: {
        title: 'Founder Mode — from idea to launch artifacts in one afternoon',
        description: 'Guided cofounder that walks you from lean canvas to validated landing page brief, end-to-end.',
        og_image_alt: null,
        json_ld_type: 'Product',
    },
    performance_floor: {
        lcp_max_seconds: 2.5,
        cls_max: 0.1,
        lighthouse_a11y_min: 95,
        notes: [],
    },
    instrumentation: {
        sdk_install_cmd: 'pnpm add posthog-js',
        init_notes: [],
        identify_notes: [],
        custom_events: [],
        privacy_notes: [],
    },
    global_acceptance_criteria: [],
}

export function FounderModeLandingPreview(): JSX.Element {
    return (
        <main className="fixed inset-0 top-[54px] overflow-y-auto bg-bg-3000">
            <div className="max-w-5xl mx-auto p-6 flex flex-col gap-4">
                <header>
                    <h1 className="text-xl font-semibold">Landing page mockup — preview</h1>
                    <p className="text-sm text-text-secondary mt-1">
                        Visual sandbox for{' '}
                        <code className="text-xs px-1 py-0.5 rounded bg-fill-highlight-100 border border-border">
                            LandingPageMockup
                        </code>{' '}
                        rendered against a hardcoded mock spec. Not part of the founder flow yet.
                    </p>
                </header>
                <LandingPageMockup spec={MOCK_SPEC} />
            </div>
        </main>
    )
}

export const scene: SceneExport = {
    component: FounderModeLandingPreview,
}

export default FounderModeLandingPreview
