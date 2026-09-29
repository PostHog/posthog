import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { AnswerMessage } from './AnswerMessage'

const QUERY_RESPONSE = {
    results: [
        ['2026-09-27', 120],
        ['2026-09-28', 180],
        ['2026-09-29', 150],
    ],
    columns: ['day', 'pageviews'],
    types: [
        ['day', 'Date'],
        ['pageviews', 'UInt64'],
    ],
}

const meta: Meta<typeof AnswerMessage> = {
    title: 'Products/PostHog AI/AnswerMessage',
    component: AnswerMessage,
    args: {
        id: 'example-answer',
        content: [
            'Pageviews went up after the launch:',
            '<hogql display="block" title="Daily pageviews, last 3 days" caption="Includes today">SELECT toDate(timestamp) AS day, count() AS pageviews FROM events GROUP BY day ORDER BY day</hogql>',
            'Most of the growth came on the first day.',
        ].join('\n\n'),
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': () => [200, QUERY_RESPONSE],
                '/api/environments/:team_id/query/:query_kind/': () => [200, QUERY_RESPONSE],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof AnswerMessage>

export const WithQueryChart: Story = {}
