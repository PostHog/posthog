import type { SubscriptionDeliveryApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { insightCriteriaNote } from './SubscriptionDeliveryHistory'

const criteria = (sent: number, excludedNames: string[]): Record<string, unknown> => ({
    insight_criteria: {
        criteria: 'has_data',
        checked_count: sent + excludedNames.length,
        sent_count: sent,
        excluded: excludedNames.map((name) => ({ name })),
    },
})

describe('insightCriteriaNote', () => {
    it.each([
        ['skipped', criteria(0, ['A', 'B']), 'None of the 2 insights checked had data, so nothing was sent.'],
        ['skipped', criteria(0, ['A']), 'The insight checked had no data, so nothing was sent.'],
        ['completed', criteria(1, ['B']), 'Sent 1 of 2 insights checked. Left out with no data: B.'],
        ['completed', criteria(2, []), null],
        ['skipped', { insights: [] }, null],
    ])('%s delivery with %j', (status, content_snapshot, expected) => {
        const row = { status, content_snapshot } as unknown as SubscriptionDeliveryApi
        expect(insightCriteriaNote(row)).toBe(expected)
    })
})
