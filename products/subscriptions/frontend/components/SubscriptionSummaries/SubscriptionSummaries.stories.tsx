import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { PaginatedSubscriptionSummaryListApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionSummaries } from './SubscriptionSummaries'

const SUMMARIES: PaginatedSubscriptionSummaryListApi = {
    next: null,
    previous: null,
    results: [
        {
            id: 'summary-3',
            subscription: 11,
            subscription_title: 'Weekly growth review',
            target_type: 'slack',
            change_summary:
                'Weekly signups rose from 1,204 to 1,388 (+15%). Activation held steady at 41%.\nPaid conversions fell from 92 to 81, mostly on the annual plan.',
            period_start: '2026-03-30T09:00:00Z',
            created_at: '2026-04-06T09:00:00Z',
        },
        {
            id: 'summary-2',
            subscription: 12,
            subscription_title: 'Daily metrics email',
            target_type: 'email',
            change_summary: 'Daily active users fell from 3,410 to 3,120 (-9%) after the weekend.',
            period_start: '2026-04-04T08:00:00Z',
            created_at: '2026-04-05T08:00:00Z',
        },
        {
            id: 'summary-1',
            subscription: 11,
            subscription_title: 'Weekly growth review',
            target_type: 'slack',
            change_summary: 'First summary for this dashboard. Weekly signups were 1,204.',
            period_start: null,
            created_at: '2026-03-30T09:00:00Z',
        },
    ],
}

const meta: Meta<typeof SubscriptionSummaries> = {
    component: SubscriptionSummaries,
    title: 'Products/Subscriptions/Subscription summaries',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/subscriptions/summaries/': SUMMARIES,
            },
        }),
    ],
    parameters: {
        mockDate: '2026-04-07',
        featureFlags: [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES],
    },
}

export default meta

type Story = StoryObj<typeof SubscriptionSummaries>

export const LatestWithHistory: Story = {
    render: () => (
        <div className="max-w-200">
            <SubscriptionSummaries dashboardId={1} />
        </div>
    ),
}
