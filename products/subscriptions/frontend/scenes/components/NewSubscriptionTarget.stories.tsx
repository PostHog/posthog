import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { NewSubscriptionTarget } from './NewSubscriptionTarget'

const INSIGHTS = [
    { id: 11, short_id: 'ins11', name: 'Weekly active users' },
    { id: 12, short_id: 'ins12', name: 'Signup funnel' },
    { id: 13, short_id: 'ins13', name: '', derived_name: 'Pageviews by browser' },
]

const DASHBOARDS = [
    { id: 1, name: 'Weekly metrics' },
    { id: 2, name: 'Growth' },
]

const meta: Meta<typeof NewSubscriptionTarget> = {
    title: 'Products/Subscriptions/New subscription target',
    component: NewSubscriptionTarget,
    parameters: { testOptions: { viewport: { width: 720, height: 420 } } },
    decorators: [
        (Story) => {
            useStorybookMocks({
                get: {
                    '/api/projects/:team_id/insights/': { count: INSIGHTS.length, results: INSIGHTS },
                    '/api/projects/:team_id/dashboards/': { count: DASHBOARDS.length, results: DASHBOARDS },
                },
            })
            return (
                <div className="p-4 max-w-160">
                    <Story />
                </div>
            )
        },
    ],
}
export default meta

type Story = StoryObj<typeof NewSubscriptionTarget>

export const PickWhatToSend: Story = {
    args: { aiSubscriptionsAvailable: true, onCancel: () => {} },
}

export const WithoutAiPrompts: Story = {
    args: { aiSubscriptionsAvailable: false, onCancel: () => {} },
}
