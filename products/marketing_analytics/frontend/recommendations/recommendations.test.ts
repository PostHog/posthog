import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { groupRecommendations } from './recommendations'

function recommendation(overrides: Partial<MarketingAnalyticsRecommendation>): MarketingAnalyticsRecommendation {
    return {
        rule: 'spend_without_conversions',
        level: 'search_term',
        subject: 'term',
        action: 'Add it as a negative',
        reason: 'No conversions',
        impact: 100,
        impactDirection: 'save',
        impactType: 'measured',
        currency: 'USD',
        ...overrides,
    }
}

describe('groupRecommendations', () => {
    it('puts groups that only say keep last and sums impact per currency', () => {
        const groups = groupRecommendations([
            recommendation({ rule: 'brand_overlap', impactDirection: 'keep', impact: 5000 }),
            recommendation({ subject: 'a', impact: 100, currency: 'USD' }),
            recommendation({ subject: 'b', impact: 50, currency: 'USD' }),
            recommendation({ subject: 'c', impact: 90000, currency: 'EUR' }),
        ])

        expect(groups.map((group) => [group.rule, group.totals])).toEqual([
            [
                'spend_without_conversions',
                [
                    { direction: 'save', currency: 'USD', amount: 150 },
                    { direction: 'save', currency: 'EUR', amount: 90000 },
                ],
            ],
            ['brand_overlap', [{ direction: 'keep', currency: 'USD', amount: 5000 }]],
        ])
    })
})
