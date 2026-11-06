import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import {
    AIQueryPlanStatusEnumApi,
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
    prompt: 'Summarize weekly growth',
    ai_query_plan_status: AIQueryPlanStatusEnumApi.Frozen,
}

describe('SubscriptionSummary', () => {
    afterEach(() => {
        cleanup()
    })

    it('does not show current query plan state because the state belongs to each delivery', () => {
        render(<SubscriptionSummary sub={AI_SUBSCRIPTION} />)

        expect(screen.queryByText('Query plan')).not.toBeInTheDocument()
        expect(screen.queryByLabelText(/query plan/i)).not.toBeInTheDocument()
    })

    it('does not show a query plan state for a non-AI subscription', () => {
        render(<SubscriptionSummary sub={MOCK_SUBSCRIPTION_INSIGHT} />)

        expect(screen.queryByText('Query plan')).not.toBeInTheDocument()
        expect(screen.queryByLabelText(/query plan/i)).not.toBeInTheDocument()
    })
})
