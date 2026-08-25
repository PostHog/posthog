import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionDeliveryDestinationCell, SubscriptionDestinationCell } from './SubscriptionDestinationCell'

const TEAMS_WEBHOOK_PATH =
    '/workflows/00000000/triggers/manual/paths/invoke?api-version=2016-06-01&sig=not-a-real-signature'
const TEAMS_WEBHOOK_HOST = 'prod-12.westeurope.logic.azure.com'
const TEAMS_WEBHOOK_URL = `https://${TEAMS_WEBHOOK_HOST}${TEAMS_WEBHOOK_PATH}`

describe('SubscriptionDestinationCell', () => {
    it.each([
        ['a webhook URL', TEAMS_WEBHOOK_URL],
        // The canonical Azure form carries :443. Keeping it here would label the same destination
        // differently from the delivery history, which shows the bare host.
        ['a webhook URL with an explicit port', `https://${TEAMS_WEBHOOK_HOST}:443${TEAMS_WEBHOOK_PATH}`],
    ])('shows %s by host and nothing that authorizes a post', (_label, targetValue) => {
        const { container } = render(
            <SubscriptionDestinationCell sub={{ target_type: 'teams', target_value: targetValue } as SubscriptionApi} />
        )

        expect(container.textContent).toBe(TEAMS_WEBHOOK_HOST)
        // A long host truncates in the cell, so the tooltip is the only way to read it in full.
        expect(container.firstElementChild).toHaveAttribute('title', TEAMS_WEBHOOK_HOST)
        // innerHTML, not textContent, so DOM attributes such as title are covered too.
        expect(container.innerHTML).not.toContain('sig=')
        expect(container.innerHTML).not.toContain('/workflows/')
    })

    it.each([
        ['the host the API masked the webhook to', TEAMS_WEBHOOK_HOST],
        ['the placeholder the API sends when the webhook URL did not parse', 'webhook'],
    ])('shows a Teams delivery as %s', (_label, targetValue) => {
        const { container } = render(
            <SubscriptionDeliveryDestinationCell targetType="teams" targetValue={targetValue} />
        )

        expect(container.textContent).toBe(targetValue)
    })
})
