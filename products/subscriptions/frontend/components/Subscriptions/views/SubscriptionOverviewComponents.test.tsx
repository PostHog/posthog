import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { SubscriptionResourceTypes, SubscriptionType } from '~/types'

import { SubscriptionListItem } from './SubscriptionOverviewComponents'

const TEAMS_WEBHOOK_URL =
    'https://prod-12.westeurope.logic.azure.com/workflows/00000000/triggers/manual/paths/invoke?api-version=2016-06-01&sig=not-a-real-signature'

const teamsSubscription: SubscriptionType = {
    id: 1,
    resource_type: SubscriptionResourceTypes.Insight,
    target_type: 'teams',
    target_value: TEAMS_WEBHOOK_URL,
    frequency: 'weekly',
    interval: 1,
    byweekday: null,
    bysetpos: null,
    start_date: '2026-01-01T09:00:00Z',
    title: 'Weekly report',
    summary: 'every week on Monday',
    next_delivery_date: null,
    created_at: '2026-01-01T09:00:00Z',
    created_by: null,
    enabled: true,
}

describe('SubscriptionListItem', () => {
    it('names a Microsoft Teams destination by host and keeps the webhook URL out of the DOM', () => {
        const { container } = render(<SubscriptionListItem subscription={teamsSubscription} onClick={() => {}} />)

        expect(container.textContent).toContain('prod-12.westeurope.logic.azure.com')
        // innerHTML, not textContent, so DOM attributes such as title are covered too.
        expect(container.innerHTML).not.toContain('sig=')
        expect(container.innerHTML).not.toContain('/workflows/')
    })
})
