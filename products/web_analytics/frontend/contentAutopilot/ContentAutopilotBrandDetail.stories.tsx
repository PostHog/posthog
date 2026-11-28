import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOBrandApi, AEOBrandDetailApi } from '../generated/api.schemas'
import { ContentAutopilot } from './ContentAutopilot'
import { type BrandDetailTab, contentAutopilotBrandDetailLogic } from './contentAutopilotBrandDetailLogic'
import { EXAMPLE_ENGINE_SETTINGS, EXAMPLE_PROMPT_TOPICS, EXAMPLE_SETUP_CONTEXT } from './contentAutopilotStoryFixtures'

const brandOf = (id: string, name: string, domain: string, kind: AEOBrandApi['kind']): AEOBrandApi => ({
    id,
    name,
    domain,
    kind,
    status: 'confirmed',
    source: 'manual',
    aliases: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
})

const RIVAL = brandOf('0193a6f1-0000-0000-0000-000000000001', 'Rival Analytics', 'rival.example.org', 'competitor')
const CATALOG: AEOBrandApi[] = [
    brandOf('0193a6f1-0000-0000-0000-000000000010', 'Hedgebox', 'example.com', 'own'),
    RIVAL,
    brandOf('0193a6f1-0000-0000-0000-000000000002', 'Metricsly', 'metrics.example.net', 'competitor'),
    brandOf('0193a6f1-0000-0000-0000-000000000003', 'Review Hub', 'reviews.example.io', 'publisher'),
]

const prompt = (
    index: number,
    text: string,
    topic: string | null,
    rate: number,
    engines: string[]
): AEOBrandDetailApi['prompts'][number] => ({
    id: `00000000-0000-4000-8000-0000000005${String(index).padStart(2, '0')}`,
    text,
    topic,
    answers: 60,
    answers_mentioning: Math.round(rate * 60),
    mention_rate: rate,
    engines,
})

const page = (url: string, share: number): AEOBrandDetailApi['cited_sites'][number]['pages'][number] => ({
    url,
    answers: Math.round(share * 300),
    share_of_answers: share,
})

const BRAND_DETAIL: AEOBrandDetailApi = {
    brand: RIVAL,
    domains: ['rival.example.org'],
    window_from: '2026-10-01',
    window_to: '2026-10-30',
    days: 30,
    branded: 'non_branded',
    engine: null,
    topic: null,
    current: {
        answers: 1240,
        answers_mentioning: 300,
        visibility: 0.242,
        citation_rate: 0.118,
        average_position: 2.6,
        positive_share: 0.71,
    },
    previous: {
        answers: 1180,
        answers_mentioning: 255,
        visibility: 0.216,
        citation_rate: 0.124,
        average_position: 3.1,
        positive_share: 0.74,
    },
    latest_date: '2026-10-30',
    latest: {
        answers: 41,
        answers_mentioning: 11,
        visibility: 0.268,
        citation_rate: 0.122,
        average_position: 2.2,
        positive_share: 0.8,
    },
    days_with_answers: 30,
    prompts: [
        prompt(1, 'What is the best product analytics tool for a startup?', 'Product analytics', 0.62, [
            'claude-web-search',
            'openai-web-search',
            'perplexity-web-search',
        ]),
        prompt(2, 'Which analytics tools have a generous free tier?', 'Pricing', 0.45, ['openai-web-search']),
        prompt(3, 'How do I compare funnel analysis tools?', 'Product analytics', 0.31, [
            'claude-web-search',
            'openai-web-search',
        ]),
        prompt(4, 'What are alternatives to a self-hosted analytics stack?', null, 0.18, ['perplexity-web-search']),
        prompt(5, 'Which session replay tools work with React?', 'Session replay', 0.07, ['claude-web-search']),
    ],
    cited_sites: [
        {
            domain: 'rival.example.org',
            answers: 146,
            share_of_answers: 0.487,
            relation: 'owned',
            pages: [
                page('https://rival.example.org/pricing', 0.31),
                page('https://rival.example.org/docs/funnels', 0.18),
                page('https://rival.example.org/blog/free-tier', 0.064),
            ],
        },
        {
            domain: 'reviews.example.io',
            answers: 98,
            share_of_answers: 0.327,
            relation: 'other',
            pages: [page('https://reviews.example.io/analytics/rival', 0.29)],
        },
        {
            domain: 'example.com',
            answers: 61,
            share_of_answers: 0.203,
            relation: 'competitor',
            pages: [page('https://example.com/product-analytics', 0.15), page('https://example.com/pricing', 0.08)],
        },
        {
            domain: 'metrics.example.net',
            answers: 22,
            share_of_answers: 0.073,
            relation: 'competitor',
            pages: [page('https://metrics.example.net/compare', 0.073)],
        },
    ],
    sentiment: {
        scored: 240,
        positive_share: 0.71,
        neutral_share: 0.21,
        negative_share: 0.08,
        examples: [
            {
                sentence: 'Rival Analytics is a strong pick for small teams that want funnels out of the box.',
                sentiment: 'positive',
                engine: 'openai-web-search',
                prompt_id: '00000000-0000-4000-8000-000000000501',
            },
            {
                sentence: 'Rival Analytics also offers a hosted plan with session recordings.',
                sentiment: 'neutral',
                engine: 'claude-web-search',
                prompt_id: '00000000-0000-4000-8000-000000000503',
            },
            {
                sentence: 'Some reviewers find Rival Analytics slow to load on large projects.',
                sentiment: 'negative',
                engine: 'perplexity-web-search',
                prompt_id: '00000000-0000-4000-8000-000000000502',
            },
        ],
    },
    searches: [
        {
            query: 'rival analytics pricing',
            answers: 120,
            share_of_answers: 0.4,
            prompts: 3,
            engines: ['claude-web-search', 'openai-web-search'],
        },
        {
            query: 'best product analytics startup',
            answers: 84,
            share_of_answers: 0.28,
            prompts: 2,
            engines: ['openai-web-search'],
        },
        {
            query: 'rival analytics vs hedgebox',
            answers: 21,
            share_of_answers: 0.07,
            prompts: 1,
            engines: ['claude-web-search'],
        },
    ],
}

const handlers = ({ notFound = false }: { notFound?: boolean } = {}): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/aeo_brands/': ({ request }) => {
                const kind = new URL(request.url).searchParams.get('kind')
                const results = CATALOG.filter((brand) => !kind || brand.kind === kind)
                return [200, { count: results.length, next: null, previous: null, results }]
            },
            '/api/projects/:team_id/aeo_brands/:id/detail/': () =>
                notFound ? [404, { detail: 'Not found.' }] : [200, BRAND_DETAIL],
            '/api/projects/:team_id/aeo_prompts/': () => [200, { count: 0, next: null, previous: null, results: [] }],
            '/api/projects/:team_id/aeo_prompts/topics/': () => [200, EXAMPLE_PROMPT_TOPICS],
            '/api/projects/:team_id/aeo_engines/': () => [200, EXAMPLE_ENGINE_SETTINGS],
            '/api/projects/:team_id/aeo_setup/context/': () => [200, EXAMPLE_SETUP_CONTEXT],
        },
    })

const meta: Meta<typeof ContentAutopilot> = {
    title: 'Products/Web Analytics/Content autopilot/Brand page',
    component: ContentAutopilot,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        mockDate: '2026-10-30',
        pageUrl: `/web/ai-visibility/brands/${RIVAL.id}?branded=non_branded`,
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="content-autopilot-brand-kpis"]' },
    },
    decorators: [handlers()],
}

export default meta

const BrandPageStory = ({ tab = 'prompts', width }: { tab?: BrandDetailTab; width?: number }): JSX.Element => {
    const { setTab } = useActions(contentAutopilotBrandDetailLogic)
    useEffect(() => {
        setTab(tab)
    }, [setTab, tab])
    return (
        <div className="p-6" style={width ? { width } : undefined}>
            <ContentAutopilot />
        </div>
    )
}

export const Prompts: StoryFn<typeof ContentAutopilot> = () => <BrandPageStory />

export const Citations: StoryFn<typeof ContentAutopilot> = () => <BrandPageStory tab="citations" />

export const Sentiment: StoryFn<typeof ContentAutopilot> = () => <BrandPageStory tab="sentiment" />

export const Searches: StoryFn<typeof ContentAutopilot> = () => <BrandPageStory tab="searches" />

// A scene beside an open side panel on a laptop is about this wide.
export const Narrow: StoryFn<typeof ContentAutopilot> = () => <BrandPageStory width={520} />

export const NotFound: StoryFn<typeof ContentAutopilot> = () => <BrandPageStory />
NotFound.decorators = [handlers({ notFound: true })]
NotFound.parameters = {
    testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="content-autopilot-page-header"]' },
}
