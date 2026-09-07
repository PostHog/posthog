import { Meta, StoryObj } from '@storybook/react'

import {
    AiQueryPlanStatusEnumApi,
    SubscriptionResourceTypeEnumApi,
    type SubscriptionApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { MOCK_SUBSCRIPTION_INSIGHT } from './subscriptionStoryFixtures'
import { SubscriptionSummary } from './SubscriptionSummary'

const AI_SUBSCRIPTION: SubscriptionApi = {
    ...MOCK_SUBSCRIPTION_INSIGHT,
    id: 42,
    resource_type: SubscriptionResourceTypeEnumApi.AiPrompt,
    insight: null,
    insight_short_id: null,
    resource_name: 'Weekly growth report',
    prompt: 'Summarize weekly growth and flag any anomalies.',
    ai_query_plan_status: AiQueryPlanStatusEnumApi.Frozen,
}

const QUERY_PLAN_STATES = [
    ['Frozen', AiQueryPlanStatusEnumApi.Frozen],
    ['Not frozen', AiQueryPlanStatusEnumApi.NotFrozen],
    ['Planner updated', AiQueryPlanStatusEnumApi.PlannerUpdated],
] as const

const meta: Meta<typeof SubscriptionSummary> = {
    component: SubscriptionSummary,
    title: 'Products/Subscriptions/Subscription summary',
    parameters: {
        mockDate: '2026-04-07',
        layout: 'padded',
    },
}

export default meta

type Story = StoryObj<typeof SubscriptionSummary>

export const QueryPlanStates: Story = {
    render: () => (
        <div className="flex max-w-7xl flex-col gap-6">
            {QUERY_PLAN_STATES.map(([label, status], index) => (
                <section key={status} className="rounded border bg-surface-primary p-4">
                    <h3 className="mb-4 text-sm font-semibold">{label}</h3>
                    <SubscriptionSummary
                        sub={{ ...AI_SUBSCRIPTION, id: AI_SUBSCRIPTION.id + index, ai_query_plan_status: status }}
                    />
                </section>
            ))}
        </div>
    ),
}
