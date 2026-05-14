import { urls } from 'scenes/urls'

import type { FileSystemIconType } from '~/queries/schema/schema-general'

import type { LandingPageBuildSpec } from './founderLandingPageLogic'

export type RecommendationPriority = 'critical' | 'recommended' | 'nice-to-have'

export interface ProductRecommendation {
    productKey: string
    name: string
    tagline: string
    priority: RecommendationPriority
    why: string
    firstActions: string[]
    sourceContext: string[]
    iconType: FileSystemIconType
    url: string
    docsUrl: string
}

const AI_FEATURE_RE = /\b(ai|llm|agent|prompt|generative|gpt|claude|gemini|model)\b/i

const slugify = (s: string): string =>
    s
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')

const unique = <T>(xs: T[]): T[] => Array.from(new Set(xs))

export function recommendProducts(spec: LandingPageBuildSpec): ProductRecommendation[] {
    const recs: ProductRecommendation[] = []

    const allEvents = unique([
        ...spec.page_sections.flatMap((s) => s.posthog_events),
        ...spec.instrumentation.custom_events.map((e) => e.name),
    ])

    // Product analytics — always critical
    recs.push({
        productKey: 'product-analytics',
        name: 'Product analytics',
        tagline: 'Capture every interaction, build funnels, watch retention.',
        priority: 'critical',
        why:
            allEvents.length > 0
                ? `Your build spec lists ${allEvents.length} event${allEvents.length === 1 ? '' : 's'} across ${spec.page_sections.length} page section${spec.page_sections.length === 1 ? '' : 's'}. Product analytics is what makes those events answer questions.`
                : 'Every founder ships blind without basic event capture. Start here even if the spec is light on events — pageview + primary CTA gets you 80% of the way.',
        firstActions: [
            `Install with \`${spec.instrumentation.sdk_install_cmd}\` and call posthog.init() in your root layout.`,
            allEvents.length > 0
                ? `Capture these first: ${allEvents.slice(0, 4).join(', ')}${allEvents.length > 4 ? '…' : ''}`
                : 'Capture $pageview and your primary CTA click.',
            'Build a funnel: pageview → primary CTA → signup. Drop-off tells you where to iterate.',
        ],
        sourceContext: allEvents.slice(0, 6).map((e) => `event: ${e}`),
        iconType: 'product_analytics',
        url: urls.savedInsights(),
        docsUrl: 'https://posthog.com/docs/product-analytics',
    })

    // Session replay — almost always critical for v1 landing pages
    const heroSnippet = spec.project_brief.one_line_value_prop.text.slice(0, 80)
    recs.push({
        productKey: 'session-replay',
        name: 'Session replay',
        tagline: 'Watch what your first 100 visitors actually do.',
        priority: 'critical',
        why: `LLM-drafted copy is rarely right on day one. Watching 10 sessions of "${spec.project_name}" will tell you what no funnel can — where attention dies on the page.`,
        firstActions: [
            'Enable session_recording in your posthog.init() config.',
            "Filter recordings to visitors who hit the landing page but didn't click your primary CTA.",
            'Block 30 minutes on day 1 to watch the first 10. Repeat on day 7.',
        ],
        sourceContext: [
            `hero: "${heroSnippet}${heroSnippet.length < spec.project_brief.one_line_value_prop.text.length ? '…' : ''}"`,
        ],
        iconType: 'session_replay',
        url: urls.replay(),
        docsUrl: 'https://posthog.com/docs/session-replay',
    })

    // Surveys — if any pain lacks quantitative evidence
    const unquantifiedPains = spec.project_brief.top_user_pains.filter((p) => !p.quantitative_evidence)
    if (unquantifiedPains.length > 0) {
        recs.push({
            productKey: 'surveys',
            name: 'Surveys',
            tagline: 'Turn assumed pain into real customer evidence.',
            priority: 'recommended',
            why: `${unquantifiedPains.length} of your ${spec.project_brief.top_user_pains.length} pain points have no quantitative evidence yet. A 3-question survey on the landing page closes that gap in a week.`,
            firstActions: [
                'Ask: "What\'s the biggest reason you\'re stuck on this today?"',
                "Target visitors who scrolled past the hero but didn't click the primary CTA.",
                ...unquantifiedPains.slice(0, 2).map((p) => `Pressure-test the pain: "${p.label}"`),
            ],
            sourceContext: unquantifiedPains.slice(0, 3).map((p) => `pain: ${p.label}`),
            iconType: 'survey',
            url: urls.surveys(),
            docsUrl: 'https://posthog.com/docs/surveys',
        })
    }

    // Experiments — multi-angle messaging warrants A/B testing
    const highKeywords = spec.seo_keywords.filter((k) => k.priority === 'high')
    if (highKeywords.length >= 2 || spec.project_brief.proof_points.length >= 3) {
        const altHeadline = spec.project_brief.proof_points[0]?.statement.replace(/^["']|["']$/g, '').slice(0, 80)
        recs.push({
            productKey: 'experiments',
            name: 'Experiments',
            tagline: "A/B test the messaging that's working hardest.",
            priority: 'recommended',
            why: `You have ${spec.project_brief.proof_points.length} proof points and ${highKeywords.length} high-priority keywords. The headline you ship is one of many plausible angles — test it.`,
            firstActions: [
                `Variant A: current headline — "${heroSnippet}${heroSnippet.length < spec.project_brief.one_line_value_prop.text.length ? '…' : ''}"`,
                altHeadline
                    ? `Variant B: lead with your strongest proof — "${altHeadline}${altHeadline.length === 80 ? '…' : ''}"`
                    : 'Variant B: a sharper, more outcome-led headline.',
                'Primary metric: primary CTA clicks. Run to 200 visitors per variant.',
            ],
            sourceContext: highKeywords.map((k) => `keyword: ${k.phrase} (${k.priority})`),
            iconType: 'experiment',
            url: urls.experiments(),
            docsUrl: 'https://posthog.com/docs/experiments',
        })
    }

    // Feature flags — if optional sections were included
    const optionalIncluded = spec.page_sections.filter((s) => s.classification === 'optional_included')
    if (optionalIncluded.length > 0) {
        recs.push({
            productKey: 'feature-flags',
            name: 'Feature flags',
            tagline: "Ship optional sections behind a flag. Kill the ones that don't pull weight.",
            priority: 'recommended',
            why: `${optionalIncluded.length} optional section${optionalIncluded.length === 1 ? '' : 's'} made the build — "${optionalIncluded
                .map((s) => s.name)
                .join(
                    '", "'
                )}". Gate ${optionalIncluded.length === 1 ? 'it' : 'each'} behind a flag so you can measure lift before committing.`,
            firstActions: optionalIncluded
                .slice(0, 3)
                .map((s) => `Create flag: \`landing-page-${slugify(s.name)}\` — gate the "${s.name}" section.`),
            sourceContext: optionalIncluded.slice(0, 3).map((s) => `section: ${s.name} (optional)`),
            iconType: 'feature_flag',
            url: urls.featureFlags(),
            docsUrl: 'https://posthog.com/docs/feature-flags',
        })
    }

    // Error tracking — always recommended
    recs.push({
        productKey: 'error-tracking',
        name: 'Error tracking',
        tagline: 'Catch the JS error that kills your signup form on day one.',
        priority: 'recommended',
        why: `Half of "the page doesn't work" complaints are silent JS errors that never surface to the founder. Your performance floor (a11y ${spec.performance_floor.lighthouse_a11y_min}, LCP ${spec.performance_floor.lcp_max_seconds}s) deserves a monitoring story.`,
        firstActions: [
            'Enable error tracking in your posthog.init() config — comes with posthog-js.',
            'Set up an alert: any new error class on the landing page route notifies you immediately.',
            'Watch session replays of the first 5 errors so you see the exact UX that hit them.',
        ],
        sourceContext: [
            `a11y floor: ${spec.performance_floor.lighthouse_a11y_min}`,
            `LCP target: ${spec.performance_floor.lcp_max_seconds}s`,
        ],
        iconType: 'error_tracking',
        url: urls.errorTracking(),
        docsUrl: 'https://posthog.com/docs/error-tracking',
    })

    // LLM analytics — only if the product is AI-flavored
    const aiFeatures = spec.project_brief.top_features.filter((f) => AI_FEATURE_RE.test(f))
    if (aiFeatures.length > 0) {
        recs.push({
            productKey: 'llm-analytics',
            name: 'LLM analytics',
            tagline: 'Track tokens, latency, and cost on every model call.',
            priority: 'critical',
            why: `${aiFeatures.length} of your top feature${aiFeatures.length === 1 ? ' is' : 's are'} AI-flavored. Without LLM analytics you can't see which prompts cost the most, which fail, or which actually convert.`,
            firstActions: [
                'Wrap your model calls with the PostHog LLM SDK (drop-in for OpenAI/Anthropic SDKs).',
                'Build a dashboard for spend, latency, and pass rate by prompt.',
                'Tag each generation with the persona — see which audience the AI serves best.',
            ],
            sourceContext: aiFeatures.slice(0, 3).map((f) => `feature: ${f}`),
            iconType: 'llm_analytics',
            url: urls.llmAnalyticsDashboard(),
            docsUrl: 'https://posthog.com/docs/ai-engineering/observability',
        })
    }

    // Web analytics — nice-to-have, for the marketing-side view
    recs.push({
        productKey: 'web-analytics',
        name: 'Web analytics',
        tagline: 'A Plausible-style dashboard for the marketing side of the house.',
        priority: 'nice-to-have',
        why: `Your GTM plan implies multiple channels — keywords like "${highKeywords.map((k) => k.phrase).join('", "') || spec.seo_keywords[0]?.phrase || 'organic'}" want a clean source/medium view that doesn't need a custom funnel.`,
        firstActions: [
            'Web analytics auto-populates from your existing $pageview events — no extra setup.',
            'Bookmark the landing-page-only filter so you can glance at it daily.',
        ],
        sourceContext: spec.seo_keywords.slice(0, 3).map((k) => `keyword: ${k.phrase}`),
        iconType: 'web_analytics',
        url: urls.webAnalytics(),
        docsUrl: 'https://posthog.com/docs/web-analytics',
    })

    return recs
}

export const PRIORITY_ORDER: Record<RecommendationPriority, number> = {
    critical: 0,
    recommended: 1,
    'nice-to-have': 2,
}

export function groupByPriority(
    recs: ProductRecommendation[]
): Array<{ priority: RecommendationPriority; items: ProductRecommendation[] }> {
    const groups = new Map<RecommendationPriority, ProductRecommendation[]>()
    for (const r of recs) {
        const existing = groups.get(r.priority) ?? []
        existing.push(r)
        groups.set(r.priority, existing)
    }
    return Array.from(groups.entries())
        .sort(([a], [b]) => PRIORITY_ORDER[a] - PRIORITY_ORDER[b])
        .map(([priority, items]) => ({ priority, items }))
}
