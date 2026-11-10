import type { Meta, StoryObj } from '@storybook/react'

import type { AEOWeeklyReportApi } from '../generated/api.schemas'
import { ContentAutopilotWeeklyReportPreview } from './ContentAutopilotWeeklyReportPreview'

const APP_URL = 'https://app.example.net/project/1/web/content-autopilot'

const REPORT: AEOWeeklyReportApi = {
    window_from: '2026-11-02',
    window_to: '2026-11-08',
    previous_from: '2026-10-26',
    previous_to: '2026-11-01',
    brand_names: ['example'],
    app_url: APP_URL,
    scorecard: {
        answers: 1284,
        previous_answers: 1240,
        visibility: 0.412,
        previous_visibility: 0.386,
        visibility_change: 0.026,
        citation_rate: 0.183,
        previous_citation_rate: 0.201,
        citation_rate_change: -0.018,
    },
    topics: [
        {
            topic: 'Session replay',
            answers: 312,
            previous_answers: 298,
            visibility: 0.52,
            previous_visibility: 0.61,
            visibility_change: -0.09,
        },
        {
            topic: 'Feature flags',
            answers: 276,
            previous_answers: 280,
            visibility: 0.47,
            previous_visibility: 0.41,
            visibility_change: 0.06,
        },
        {
            topic: 'Product analytics',
            answers: 540,
            previous_answers: 520,
            visibility: 0.33,
            previous_visibility: 0.32,
            visibility_change: 0.01,
        },
        {
            topic: '',
            answers: 156,
            previous_answers: 0,
            visibility: 0.21,
            previous_visibility: null,
            visibility_change: null,
        },
    ],
    pages: [
        {
            role: 'owned_gained',
            url: 'https://example.com/docs/feature-flags/rollouts',
            domain: 'example.com',
            topic: 'Feature flags',
            citation_rate: 0.22,
            previous_citation_rate: 0.12,
            change: 0.1,
        },
        {
            role: 'owned_lost',
            url: 'https://example.com/blog/session-replay-guide',
            domain: 'example.com',
            topic: 'Session replay',
            citation_rate: 0.08,
            previous_citation_rate: 0.19,
            change: -0.11,
        },
        {
            role: 'competitor_gained',
            url: 'https://rival.example.org/replay/pricing',
            domain: 'rival.example.org',
            topic: 'Session replay',
            citation_rate: 0.27,
            previous_citation_rate: 0.14,
            change: 0.13,
        },
    ],
    actions: [
        {
            kind: 'update_owned_page',
            text: 'Update example.com/blog/session-replay-guide: its citations in Session replay fell 11 pts.',
            url: APP_URL,
            topic: 'Session replay',
            page_url: 'https://example.com/blog/session-replay-guide',
            compare_url: null,
        },
        {
            kind: 'review_competitor_page',
            text: 'Review rival.example.org/replay/pricing against your example.com/blog/session-replay-guide: it gained 13 pts in Session replay.',
            url: APP_URL,
            topic: 'Session replay',
            page_url: 'https://rival.example.org/replay/pricing',
            compare_url: 'https://example.com/blog/session-replay-guide',
        },
        {
            kind: 'check_topic',
            text: 'Session replay fell 9 pts: check its prompts in AI visibility.',
            url: APP_URL,
            topic: 'Session replay',
            page_url: null,
            compare_url: null,
        },
    ],
}

const meta: Meta<typeof ContentAutopilotWeeklyReportPreview> = {
    title: 'Products/Web Analytics/Content autopilot/Weekly report preview',
    component: ContentAutopilotWeeklyReportPreview,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        // Matches the width of the preview modal.
        (Story) => (
            <div className="max-w-[720px] p-4">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ContentAutopilotWeeklyReportPreview>

export const Default: Story = { args: { report: REPORT } }

export const QuietWeek: Story = {
    args: {
        report: {
            ...REPORT,
            topics: REPORT.topics.map((topic) => ({ ...topic, visibility_change: 0 })),
            pages: [],
            actions: [],
        },
    },
}
