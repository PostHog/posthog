import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { groupRecommendations, summarizeImpact } from './recommendations'

function recommendation(overrides: Partial<MarketingAnalyticsRecommendation>): MarketingAnalyticsRecommendation {
    return {
        rule: 'spend_without_conversions',
        level: 'search_term',
        subject: 'term',
        identity: {
            rule: 'spend_without_conversions',
            source_type: 'google_ads',
            customer_id: '111',
            campaign_id: '',
            subject: 'term',
        },
        key: 'key-term',
        action: 'Add it as a negative',
        reason: 'No conversions',
        impact: 100,
        impactDirection: 'save',
        impactType: 'measured',
        currency: 'USD',
        ...overrides,
    }
}

describe('recommendations', () => {
    it('groups by rule, puts groups that only say keep last and sums impact per currency', () => {
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

    const campaignRow = (
        rule: MarketingAnalyticsRecommendation['rule'],
        campaign: string,
        impact: number,
        impactDirection: MarketingAnalyticsRecommendation['impactDirection']
    ): MarketingAnalyticsRecommendation =>
        recommendation({ rule, level: 'campaign', subject: campaign, impact, impactDirection })

    it.each([
        {
            name: 'a reviewed campaign counts its savings once',
            rows: [
                campaignRow('review_campaign', 'Generic', 1000, 'save'),
                recommendation({ subject: 'waste', campaign: 'Generic', impact: 300 }),
                campaignRow('brand_leak', 'Generic', 200, 'save'),
                recommendation({ subject: 'other', campaign: 'Other', impact: 50 }),
            ],
            expected: [{ direction: 'save', currency: 'USD', amount: 1050 }],
        },
        {
            name: 'two budget raises on one campaign count once, and new keywords add up',
            rows: [
                campaignRow('scale_campaign', 'Generic', 900, 'invest'),
                campaignRow('budget_constrained', 'Generic', 600, 'invest'),
                recommendation({
                    rule: 'keyword_gap',
                    subject: 'funnel',
                    campaign: 'Generic',
                    impact: 100,
                    impactDirection: 'invest',
                }),
            ],
            expected: [{ direction: 'invest', currency: 'USD', amount: 1000 }],
        },
        {
            name: 'keep and zero amounts stay out',
            rows: [
                campaignRow('brand_overlap', 'Brand', 5000, 'keep'),
                recommendation({ rule: 'striking_distance', subject: 'page', impact: 0, impactDirection: 'gain' }),
                recommendation({ subject: 'waste', impact: 40 }),
            ],
            expected: [{ direction: 'save', currency: 'USD', amount: 40 }],
        },
    ])('summarizeImpact: $name', ({ rows, expected }) => {
        expect(summarizeImpact(rows)).toEqual(expected)
    })
})
