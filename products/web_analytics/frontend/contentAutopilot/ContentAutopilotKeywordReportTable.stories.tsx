import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOKeywordApi, AEOKeywordReportApi, AEOKeywordReportRowApi } from '../generated/api.schemas'
import { ContentAutopilotKeywordReportTable } from './ContentAutopilotKeywordReportTable'

const row = (keyword: string, overrides: Partial<AEOKeywordReportRowApi>): AEOKeywordReportRowApi => ({
    keyword,
    prompts: 0,
    prompt_checks: 0,
    prompt_mention_rate: null,
    prompt_cited_rate: null,
    searched_checks: 0,
    searched_rate: 0,
    searched_cited_rate: null,
    answer_checks: 0,
    answer_rate: 0,
    uses_per_answer: null,
    answer_mention_rate: null,
    avg_citation_position: null,
    median_first_mention_depth: null,
    ...overrides,
})

const SMALL_RUN_REPORT: AEOKeywordReportApi = {
    days: 7,
    window_from: '2026-09-24',
    window_to: '2026-09-30',
    answers: 16,
    brand_names: ['example'],
    keywords: [
        row('product analytics', {
            prompts: 3,
            prompt_checks: 6,
            prompt_mention_rate: 0.5,
            prompt_cited_rate: 0.33,
            searched_checks: 7,
            searched_rate: 0.44,
            searched_cited_rate: 0.43,
            answer_checks: 9,
            answer_rate: 0.56,
            uses_per_answer: 2.1,
            answer_mention_rate: 0.67,
            avg_citation_position: 2.5,
            median_first_mention_depth: 0.22,
        }),
        row('session replay', {
            prompts: 1,
            prompt_checks: 2,
            prompt_mention_rate: 1,
            prompt_cited_rate: 0.5,
            searched_checks: 1,
            searched_rate: 0.06,
            searched_cited_rate: 1,
            answer_checks: 2,
            answer_rate: 0.13,
            uses_per_answer: 1,
            answer_mention_rate: 1,
            avg_citation_position: 1,
            median_first_mention_depth: 0.05,
        }),
        row('feature flags', {
            searched_checks: 3,
            searched_rate: 0.19,
            searched_cited_rate: 0,
            answer_checks: 1,
            answer_rate: 0.06,
            uses_per_answer: 1,
            answer_mention_rate: 0,
        }),
        row('self-hosted', {}),
    ],
}

const KEYWORDS: AEOKeywordApi[] = SMALL_RUN_REPORT.keywords.map(({ keyword }, index) => ({
    id: `kw-${index}`,
    keyword,
    created_at: '2026-09-20T10:00:00Z',
}))

const meta: Meta<typeof ContentAutopilotKeywordReportTable> = {
    title: 'Products/Web Analytics/Content autopilot/Keyword report table',
    component: ContentAutopilotKeywordReportTable,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        mockDate: '2026-09-30',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="content-autopilot-keywords-report"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/aeo_keywords/': () => [200, KEYWORDS],
                '/api/projects/:team_id/aeo_keywords/report/': () => [200, SMALL_RUN_REPORT],
                '/api/projects/:team_id/aeo_keywords/modifiers/': () => [200, { answers: 0, modifiers: [] }],
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [200, { tables: {}, joins: [] }],
            },
        }),
    ],
}

export default meta

export const TooFewAnswers: StoryFn<typeof ContentAutopilotKeywordReportTable> = () => (
    <div className="@container/keywords p-6">
        <ContentAutopilotKeywordReportTable />
    </div>
)
