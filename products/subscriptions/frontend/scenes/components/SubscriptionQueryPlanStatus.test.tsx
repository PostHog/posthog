import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { AIQueryPlanStatusEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionQueryPlanStatus } from './SubscriptionQueryPlanStatus'

const EXPECTED_COPY = {
    [AIQueryPlanStatusEnumApi.Frozen]:
        'Frozen query plan. PostHog will reuse these query definitions for each delivery. Date ranges, results, and the written report will still update. PostHog generates a new plan when you edit the prompt or when the query planner is updated.',
    [AIQueryPlanStatusEnumApi.NotFrozen]:
        'Query plan not frozen. No reusable plan is available yet. PostHog will freeze the plan when it can be safely reused.',
    [AIQueryPlanStatusEnumApi.PlannerUpdated]:
        'Query plan will be regenerated. The query planner changed. The next successful delivery will freeze a new plan.',
} as const

describe('SubscriptionQueryPlanStatus', () => {
    afterEach(() => {
        cleanup()
    })

    it.each(Object.entries(EXPECTED_COPY))(
        'renders an accessible %s status with its explanation',
        async (status, copy) => {
            render(<SubscriptionQueryPlanStatus status={status as AIQueryPlanStatusEnumApi} />)

            const indicator = screen.getByRole('img', { name: copy })
            expect(indicator).toHaveAttribute('tabindex', '0')
            expect(indicator.querySelector('svg')).toBeInTheDocument()

            fireEvent.pointerEnter(indicator, { pointerType: 'mouse' })
            fireEvent.mouseEnter(indicator)

            expect(await screen.findByText(copy)).toBeInTheDocument()
        }
    )

    it('shows the explanation when focused from the keyboard', async () => {
        const copy = EXPECTED_COPY[AIQueryPlanStatusEnumApi.Frozen]
        render(<SubscriptionQueryPlanStatus status={AIQueryPlanStatusEnumApi.Frozen} />)

        fireEvent.focus(screen.getByRole('img', { name: copy }))

        expect(await screen.findByText(copy)).toBeInTheDocument()
    })

    it.each([
        ['null', null],
        ['undefined', undefined],
        ['unknown', 'future_status' as AIQueryPlanStatusEnumApi],
    ])('renders nothing for a %s status', (_name, status) => {
        const { container } = render(<SubscriptionQueryPlanStatus status={status} />)

        expect(container).toBeEmptyDOMElement()
    })
})
