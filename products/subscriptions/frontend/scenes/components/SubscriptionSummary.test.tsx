import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

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
    prompt: 'Summarize weekly growth',
    ai_query_plan_status: AiQueryPlanStatusEnumApi.Frozen,
}

describe('SubscriptionSummary', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the current query plan state for an AI prompt subscription', () => {
        render(<SubscriptionSummary sub={AI_SUBSCRIPTION} />)

        expect(screen.getByText('Query plan')).toBeInTheDocument()
        expect(screen.getByRole('img', { name: /^Frozen query plan\./ })).toBeInTheDocument()
    })

    it('does not show a query plan state for a non-AI subscription', () => {
        render(<SubscriptionSummary sub={MOCK_SUBSCRIPTION_INSIGHT} />)

        expect(screen.queryByText('Query plan')).not.toBeInTheDocument()
        expect(screen.queryByRole('img', { name: /query plan/i })).not.toBeInTheDocument()
    })
})
