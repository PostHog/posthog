import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import type { ProactiveHistoryEntryApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionPulseHistory } from './SubscriptionPulseHistory'

const HISTORY: ProactiveHistoryEntryApi[] = [
    {
        delivery_id: '019fd71b-1df8-0000-6b5f-2c35bb4aacc2',
        recommendation_title: 'Reduce sign-up friction',
        why_now: 'New users are leaving before they complete account setup.',
        confidence: 0.8,
        effort: 'small',
        metric_direction: 'increase',
        expected_metric_movement: 'Increase completed sign-ups.',
        citations: [{ title: 'Sign-up trend', url: 'https://example.com/sign-up-trend' }],
        artifact: {
            kind: 'draft_pr',
            status: 'adopted',
            url: 'https://example.com/draft-pr',
            prepared_at: '2026-09-08T09:00:00Z',
            adopted_at: '2026-09-09T09:00:00Z',
        },
        outcome: {
            status: 'improved',
            metric_name: 'Completed sign-ups',
            expected_metric_movement: 'completed sign-ups',
            direction: 'increase',
            baseline_value: '120',
            observed_value: '146',
            delta: '26',
            baseline_from: '2026-09-01',
            baseline_to: '2026-09-07',
            observed_from: '2026-09-09T00:00:00Z',
            observed_to: '2026-09-15T23:59:59.999999Z',
            due_at: '2026-09-16T09:00:00Z',
        },
    },
]

const meta: Meta<typeof SubscriptionPulseHistory> = {
    component: SubscriptionPulseHistory,
    title: 'Products/Subscriptions/Subscription Pulse history',
    parameters: {
        featureFlags: [FEATURE_FLAGS.PULSE],
        mockDate: '2026-09-16',
    },
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof SubscriptionPulseHistory>

export const WithOutcome: Story = {
    args: {
        history: HISTORY,
        loading: false,
        hasError: false,
    },
}

export const Pending: Story = {
    args: {
        history: [
            {
                ...HISTORY[0],
                outcome: {
                    ...HISTORY[0].outcome!,
                    status: 'pending',
                    observed_value: null,
                    delta: null,
                    observed_from: null,
                    observed_to: null,
                },
            },
        ],
        loading: false,
        hasError: false,
    },
}
