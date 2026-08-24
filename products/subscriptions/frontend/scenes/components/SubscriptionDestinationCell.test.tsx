import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionDeliveryDestinationCell, SubscriptionDestinationCell } from './SubscriptionDestinationCell'

const TEAMS_WEBHOOK_URL =
    'https://prod-12.westeurope.logic.azure.com/workflows/00000000/triggers/manual/paths/invoke?api-version=2016-06-01&sig=not-a-real-signature'

describe('SubscriptionDestinationCell', () => {
    it.each([
        [
            'a subscription row',
            <SubscriptionDestinationCell
                key="subscription"
                sub={{ target_type: 'teams', target_value: TEAMS_WEBHOOK_URL } as SubscriptionApi}
            />,
        ],
        [
            'a delivery history row',
            <SubscriptionDeliveryDestinationCell key="delivery" targetType="teams" targetValue={TEAMS_WEBHOOK_URL} />,
        ],
    ])('shows the webhook host and nothing that authorizes a post for %s', (_label, element) => {
        const { container } = render(element)

        expect(container.textContent).toBe('prod-12.westeurope.logic.azure.com')
        // innerHTML covers the title attribute, which used to carry the whole URL to anyone hovering.
        expect(container.innerHTML).not.toContain('sig=')
        expect(container.innerHTML).not.toContain('/workflows/')
    })
})
