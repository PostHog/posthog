import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { AIQueryPlanStatusEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionQueryPlanStatus } from './SubscriptionQueryPlanStatus'

const EXPECTED_COPY = {
    [AIQueryPlanStatusEnumApi.Frozen]:
        "This delivery's query plan was frozen for reuse. PostHog will reuse it for future deliveries until the prompt or query planner changes. Date ranges, results, and the written report still update.",
    [AIQueryPlanStatusEnumApi.NotFrozen]:
        "This delivery's query plan was not frozen for reuse. PostHog will generate a new plan for the next delivery.",
    [AIQueryPlanStatusEnumApi.PlannerUpdated]:
        'The query planner changed, so this delivery generated a new plan. The new plan was frozen for future deliveries.',
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
