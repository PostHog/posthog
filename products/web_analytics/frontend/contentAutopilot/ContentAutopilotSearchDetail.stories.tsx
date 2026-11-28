import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOPromptSetSearchDetailApi } from '../generated/api.schemas'
import { ContentAutopilotSearchDetail } from './ContentAutopilotSearchDetail'

const site = (domain: string, answers: number, isTarget = false): AEOPromptSetSearchDetailApi['domains'][number] => ({
    domain,
    answers,
    share_of_answers: answers / 120,
    is_target: isTarget,
})

const SEARCH_DETAIL: AEOPromptSetSearchDetailApi = {
    query: 'open source product analytics pricing',
    window_from: '2026-10-01',
    window_to: '2026-10-30',
    answers: 120,
    prompts: 14,
    cited: 31,
    engines: ['claude-web-search', 'openai-web-search'],
    domains_cited: 46,
    target_rank: 7,
    domains: [
        site('github.com', 88),
        site('acme-analytics.io', 74),
        site('hedgebox.net', 61),
        site('reviews.example.org', 52),
        site('metricsly.dev', 40),
        site('wikipedia.org', 37),
        site('example.com', 31, true),
        site('dataforge.app', 24),
        site('insightful.tools', 19),
        site('chartbase.io', 12),
    ],
    related_searches: [
        { query: 'acme analytics pricing', answers: 42, share_of_answers: 0.35 },
        { query: 'self-hosted product analytics', answers: 30, share_of_answers: 0.25 },
        { query: 'hedgebox vs acme analytics', answers: 18, share_of_answers: 0.15 },
        { query: 'product analytics free tier', answers: 9, share_of_answers: 0.075 },
    ],
    keywords: ['open source analytics', 'product analytics'],
    top_prompts: [
        { id: '00000000-0000-4000-8000-000000000401', text: 'Which open source product analytics tool is cheapest?' },
        { id: '00000000-0000-4000-8000-000000000402', text: 'What does a product analytics tool cost for a startup?' },
    ],
}

const meta: Meta<typeof ContentAutopilotSearchDetail> = {
    title: 'Products/Web Analytics/Content autopilot/Search detail',
    component: ContentAutopilotSearchDetail,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        mockDate: '2026-10-30',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="content-autopilot-search-detail"]' },
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/aeo_prompts/search_detail/': () => [200, SEARCH_DETAIL] },
        }),
    ],
}

export default meta

export const CitedSites: StoryFn<typeof ContentAutopilotSearchDetail> = () => (
    <div className="max-w-xl border rounded p-2">
        <ContentAutopilotSearchDetail
            query={SEARCH_DETAIL.query}
            dateFrom={SEARCH_DETAIL.window_from}
            dateTo={SEARCH_DETAIL.window_to}
            branded="all"
            engine={null}
            topic={null}
            onOpenPrompt={() => {}}
        />
    </div>
)
